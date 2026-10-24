from sqlmodel import Session, select

from app.models.entities import NewsArticle, NewsStatus


COMMUNITY_STORIES = (
    {
        "slug": "another-big-win-for-our-youth-financial-literacy-employment-milestones",
        "title": "A Big Win for Our Youth: Financial Literacy and New Job Offers",
        "category": "Impact Update",
        "image_url": "/static/images/news/financial-literacy.png",
        "summary": (
            "Aurorah's second youth group completed its introductory financial "
            "literacy programme, while three participants received full-time job offers."
        ),
        "content": (
            "Aurorah's second group of youth in the National Youth Service Program "
            "has completed its introductory Financial Literacy Program. Many of the "
            "participants have also been volunteering at early childhood development "
            "centres, giving their time and skills back to the community.\n\n"
            "Three of the young people have received full-time job offers. Their "
            "achievement is a reminder that youth development is about more than "
            "keeping young people busy: it is about creating opportunities, building "
            "confidence, developing skills and opening doors to employment.\n\n"
            "We are proud of these young people and of everyone who continues to "
            "show up, volunteer and learn. Thank you to the contributors and "
            "facilitators helping equip young people with skills for life.\n\n"
            "The group has completed the introductory programme and is looking "
            "forward to advanced financial literacy training."
        ),
        "is_featured": True,
    },
    {
        "slug": "aurorah-youth-community-clean-up",
        "title": "More Than a Clean-Up: Young People Take Responsibility",
        "category": "Community Outreaches",
        "image_url": "/static/images/news/mandela-day-and-youth-clean-up.png",
        "summary": (
            "Aurorah youth came together for a community clean-up and reflected "
            "on shared responsibility, Ubuntu and caring for the place they call home."
        ),
        "content": (
            "Aurorah youth took to the streets for a community clean-up—not because "
            "everything can be fixed in a day, but because change starts when people "
            "are willing to take responsibility.\n\n"
            "Afterwards, the young people reflected on feeling proud, giving back, "
            "working together and putting Ubuntu into practice. One reflection stood "
            "out: “We shouldn't just complain about our community—we must also be "
            "willing to do something about it.”\n\n"
            "A cleaner community starts with us. A stronger community starts with "
            "us. Ubuntu starts with us."
        ),
        "is_featured": False,
    },
    {
        "slug": "four-years-aurorah-community-hotspot-library-mandela-day",
        "title": "Celebrating Mandela Day and Four Years of the Community Hotspot Library",
        "category": "Community Outreaches",
        "image_url": "/static/images/news/mandela-day-and-youth-clean-up.png",
        "summary": (
            "Aurorah marked Mandela Day and four years of its Community Hotspot "
            "Library with a day of service, learning and connection."
        ),
        "content": (
            "Mandela Day was an opportunity to celebrate four years of Aurorah's "
            "Community Hotspot Library and a day of service with the community.\n\n"
            "With support from donors, partners and community members, senior-group "
            "members received winter items including blankets, hoodies, caps and "
            "scarves. Younger children received caps and took part in a day of fun, "
            "connection and learning.\n\n"
            "Fifty Aurorah youth participated, engaging with children, facilitating "
            "indigenous games and putting Ubuntu into practice. The day ended with "
            "a shared meal.\n\n"
            "The library began with a vision of giving children and young people a "
            "place to learn, grow and belong. Four years on, Aurorah remains "
            "committed to building that space with the community. Thank you to every "
            "donor, partner, volunteer, neighbour and community member who has "
            "contributed to the journey."
        ),
        "is_featured": False,
    },
    {
        "slug": "serving-hope-and-warmth-community-cook-off-supports-over-400-residents",
        "title": "A Community Cook-Off Brings Food and Warmth to Around 400 People",
        "category": "Community Outreaches",
        "image_url": "/static/images/news/community-cook-off.png",
        "summary": (
            "Aurorah's winter cook-off served around 400 people, with youth and "
            "volunteers giving their time to support neighbours."
        ),
        "content": (
            "Aurorah's community cook-off served around 400 people. The day was "
            "about more than numbers: it was also about young people and volunteers "
            "showing up with pride, care and a sense of family.\n\n"
            "Winter can be especially difficult for households facing choices "
            "between food, electricity and keeping warm. Aurorah shared its "
            "intention to continue serving through winter and invited people to "
            "donate warm items such as blankets, socks, beanies and jackets.\n\n"
            "The update also announced a planned meal for senior mothers on 12 May. "
            "Thank you to everyone who contributed and to the team and youth who "
            "gave their time to serve."
        ),
        "is_featured": False,
    },
    {
        "slug": "a-win-worth-celebrating-3-more-youth-secure-full-time-contracts",
        "title": "A Win Worth Celebrating: Three More Youth Secure Full-Time Contracts",
        "category": "Impact Update",
        "image_url": "/static/images/news/youth-employment.png",
        "summary": (
            "Three more young people secured one-year full-time contracts in "
            "Aurorah's youth programme, bringing the number who had moved forward "
            "to eight."
        ),
        "content": (
            "Aurorah is celebrating three more young people who secured one-year "
            "full-time contracts.\n\n"
            "The programme began with 50 young people on 15 July. With these "
            "contracts, eight had moved forward into employment opportunities, "
            "while 42 remained on the journey. The update celebrated each step and "
            "encouraged the young people still participating to keep showing up, "
            "learning and growing.\n\n"
            "Congratulations to the three young people. Their progress shows what "
            "can happen when young people are given opportunities, support and a "
            "chance to believe in themselves."
        ),
        "is_featured": False,
    },
)


def seed_community_stories(session: Session) -> None:
    duplicate_story = session.exec(
        select(NewsArticle).where(
            NewsArticle.slug
            == "a-win-worth-celebrating-three-more-youth-full-time-contracts"
        )
    ).first()
    if duplicate_story:
        session.delete(duplicate_story)

    for story in COMMUNITY_STORIES:
        existing = session.exec(
            select(NewsArticle).where(NewsArticle.slug == story["slug"])
        ).first()
        if existing:
            existing.image_url = story["image_url"]
            session.add(existing)
            continue

        session.add(
            NewsArticle(
                **story,
                author="Aurorah Team",
                published_date=None,
                status=NewsStatus.PUBLISHED.value,
            )
        )
