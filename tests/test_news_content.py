from tests.support import DatabaseTestCase

from sqlmodel import Session, select

from app.models.entities import NewsArticle
from app.news_content import COMMUNITY_STORIES, seed_community_stories


class CommunityNewsContentTests(DatabaseTestCase):
    def test_supplied_stories_are_seeded_once_and_duplicate_is_removed(self):
        with Session(self.engine) as session:
            seed_community_stories(session)
            session.commit()
            session.add(
                NewsArticle(
                    title="A Win Worth Celebrating: Three More Youth Secure Full-Time Contracts",
                    slug="a-win-worth-celebrating-three-more-youth-full-time-contracts",
                    category="Impact Update",
                    summary="Duplicate story",
                    content="Duplicate story",
                    status="Published",
                )
            )
            session.commit()
            seed_community_stories(session)
            session.commit()
            stories = session.exec(select(NewsArticle)).all()

        self.assertEqual(len(stories), len(COMMUNITY_STORIES))
        self.assertTrue(all(story.published_date is None for story in stories))
        slugs = {story.slug for story in stories}
        self.assertIn(
            "a-win-worth-celebrating-3-more-youth-secure-full-time-contracts",
            slugs,
        )
        self.assertNotIn(
            "a-win-worth-celebrating-three-more-youth-full-time-contracts",
            slugs,
        )
        self.assertEqual(
            len(
                [
                    story
                    for story in stories
                    if story.title
                    == "A Win Worth Celebrating: Three More Youth Secure Full-Time Contracts"
                ]
            ),
            1,
        )
        self.assertTrue(all(story.image_url for story in stories))

        response = self.client.get("/news")
        self.assertEqual(response.status_code, 200)
        self.assertIn("A Big Win for Our Youth", response.text)
        self.assertIn("Date not provided", response.text)
        self.assertNotIn("Illustrative image", response.text)
        self.assertIn("Three More Youth Secure Full-Time Contracts", response.text)
        self.assertIn("/static/images/news/financial-literacy.png", response.text)

        image = self.client.get("/static/images/news/financial-literacy.png")
        self.assertEqual(image.status_code, 200)
        self.assertTrue(image.content.startswith(b"\x89PNG\r\n\x1a\n"))

        detail = self.client.get(
            "/news/another-big-win-for-our-youth-financial-literacy-employment-milestones"
        )
        self.assertEqual(detail.status_code, 200)
        self.assertIn(
            "Three of the young people have received full-time job offers", detail.text
        )
        self.assertIn("Date not provided", detail.text)
