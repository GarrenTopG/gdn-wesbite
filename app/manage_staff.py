import argparse
import getpass
import hashlib
import secrets
import sys

from sqlmodel import Session, func, select

from app.db.session import create_db_and_tables, engine
from app.models.entities import AuditLog, AuthSession, User, UserRole

HASH_ROUNDS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), HASH_ROUNDS
    ).hex()
    return f"pbkdf2_sha256${HASH_ROUNDS}${salt}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    if len(password.encode("utf-8")) > 1024:
        return False
    try:
        algorithm, rounds, salt, expected = encoded.split("$", 3)
        if (
            algorithm != "pbkdf2_sha256"
            or not 100_000 <= int(rounds) <= 1_000_000
            or len(salt) != 32
            or len(expected) != 64
        ):
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt), int(rounds)
        ).hex()
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(actual, expected)


def read_new_password() -> str:
    password = getpass.getpass("Password (minimum 12 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if (
        len(password) < 12
        or len(password.encode("utf-8")) > 1024
        or password != confirmation
    ):
        raise ValueError(
            "Passwords must match, contain 12-1024 UTF-8 bytes, and include at least 12 characters."
        )
    return password


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage individual staff accounts.")
    subparsers = parser.add_subparsers(dest="action", required=True)
    create = subparsers.add_parser("create", help="Create a staff account.")
    create.add_argument("email")
    create.add_argument("full_name")
    create.add_argument(
        "--role",
        choices=[role.value for role in UserRole if role != UserRole.USER],
        default=UserRole.ADMINISTRATOR.value,
    )
    reset = subparsers.add_parser("reset-password", help="Set a staff account password.")
    reset.add_argument("email")
    deactivate = subparsers.add_parser("deactivate", help="Disable a staff account.")
    deactivate.add_argument("email")
    activate = subparsers.add_parser("activate", help="Enable a staff account.")
    activate.add_argument("email")
    set_role = subparsers.add_parser("set-role", help="Change a staff account role.")
    set_role.add_argument("email")
    set_role.add_argument(
        "role", choices=[role.value for role in UserRole if role != UserRole.USER]
    )
    revoke = subparsers.add_parser(
        "revoke-sessions", help="Revoke all sessions for a staff account."
    )
    revoke.add_argument("email")
    args = parser.parse_args()

    create_db_and_tables()
    with Session(engine) as session:
        email = args.email.strip().lower()
        user = session.exec(select(User).where(User.email == email)).first()

        if args.action == "create":
            if user:
                print("A staff account with that email already exists.", file=sys.stderr)
                return 1
            if not email or "@" not in email or not args.full_name.strip():
                print("A valid email and non-empty full name are required.", file=sys.stderr)
                return 1
            try:
                password_hash = hash_password(read_new_password())
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            session.add(
                User(
                    email=email,
                    full_name=args.full_name.strip(),
                    hashed_password=password_hash,
                    role=UserRole(args.role),
                    is_active=True,
                )
            )
            session.flush()
            created = session.exec(select(User).where(User.email == email)).one()
            session.add(
                AuditLog(
                    actor_identity="system-cli",
                    action="staff.create",
                    target_type="user",
                    target_id=str(created.id),
                    details=f'{{"role":"{created.role.value}"}}',
                )
            )
            session.commit()
            print(
                f"Staff account created for {email} with role {created.role.value}. "
                "MFA enrollment is required at first sign-in."
            )
            return 0

        if not user:
            print("Staff account not found.", file=sys.stderr)
            return 1
        if args.action == "reset-password":
            try:
                user.hashed_password = hash_password(read_new_password())
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            sessions = session.exec(
                select(AuthSession).where(AuthSession.user_id == user.id)
            ).all()
            for auth_session in sessions:
                session.delete(auth_session)
            action = "staff.password_reset"
        elif args.action == "set-role":
            if (
                user.is_active
                and user.role == UserRole.ADMINISTRATOR
                and UserRole(args.role) != UserRole.ADMINISTRATOR
                and session.exec(
                    select(func.count(User.id)).where(
                        User.role == UserRole.ADMINISTRATOR,
                        User.is_active.is_(True),
                    )
                ).one()
                <= 1
            ):
                print(
                    "The last active administrator cannot be demoted.",
                    file=sys.stderr,
                )
                return 1
            user.role = UserRole(args.role)
            sessions = session.exec(
                select(AuthSession).where(AuthSession.user_id == user.id)
            ).all()
            for auth_session in sessions:
                session.delete(auth_session)
            action = "staff.role_changed"
        elif args.action == "revoke-sessions":
            sessions = session.exec(
                select(AuthSession).where(AuthSession.user_id == user.id)
            ).all()
            for auth_session in sessions:
                session.delete(auth_session)
            action = "staff.sessions_revoked"
        else:
            if args.action == "deactivate":
                if (
                    user.is_active
                    and user.role == UserRole.ADMINISTRATOR
                    and session.exec(
                        select(func.count(User.id)).where(
                            User.role == UserRole.ADMINISTRATOR,
                            User.is_active.is_(True),
                        )
                    ).one()
                    <= 1
                ):
                    print(
                        "The last active administrator cannot be deactivated.",
                        file=sys.stderr,
                    )
                    return 1
            user.is_active = args.action == "activate"
            if not user.is_active:
                sessions = session.exec(
                    select(AuthSession).where(AuthSession.user_id == user.id)
                ).all()
                for auth_session in sessions:
                    session.delete(auth_session)
            action = f"staff.{args.action}"
        session.add(user)
        session.add(
            AuditLog(
                actor_id=None,
                actor_identity="system-cli",
                action=action,
                target_type="user",
                target_id=str(user.id),
                details=(
                    f'{{"role":"{user.role.value}"}}'
                    if args.action == "set-role"
                    else None
                ),
            )
        )
        session.commit()
        print(f"Staff account {args.action.replace('-', ' ')} completed for {email}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
