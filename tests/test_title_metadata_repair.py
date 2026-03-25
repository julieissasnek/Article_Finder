import unittest


class TestOpenAlexNormalization(unittest.TestCase):
    def test_reconstructs_abstract_from_inverted_index(self):
        from ingest.doi_resolver import OpenAlexClient

        client = OpenAlexClient(email="test@example.com")
        normalized = client._normalize_work(
            {
                "id": "https://openalex.org/W123",
                "doi": "https://doi.org/10.1000/test",
                "title": "Test Title",
                "publication_year": 2024,
                "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
                "abstract_inverted_index": {
                    "built": [1],
                    "environment": [3],
                    "for": [2],
                    "Test": [0],
                },
                "locations": [{"source": {"display_name": "Journal of Tests"}}],
                "open_access": {"is_oa": True, "oa_url": "https://example.com/pdf"},
                "cited_by_count": 3,
                "referenced_works": [],
                "type": "article",
            }
        )

        self.assertEqual(normalized["abstract"], "Test built for environment")
        self.assertEqual(normalized["doi"], "10.1000/test")
        self.assertEqual(normalized["venue"], "Journal of Tests")


class TestTitleMetadataRepairClient(unittest.TestCase):
    def test_prefers_candidate_with_abstract_and_year_match(self):
        from ingest.title_metadata_repair import TitleMetadataRepairClient

        client = TitleMetadataRepairClient.__new__(TitleMetadataRepairClient)
        best = client.best_match(
            title="Effects of daylight on circadian rhythm and sleep quality",
            author="Smith",
            year=2021,
            candidates=[
                {
                    "title": "Effects of daylight on circadian rhythm and sleep quality",
                    "authors": ["Smith, J."],
                    "year": 2021,
                    "doi": "10.1000/good",
                    "abstract": "Strong abstract text.",
                    "source": "crossref",
                },
                {
                    "title": "Daylight and office productivity",
                    "authors": ["Jones, P."],
                    "year": 2015,
                    "doi": "10.1000/bad",
                    "abstract": "",
                    "source": "semantic_scholar",
                },
            ],
        )

        self.assertIsNotNone(best)
        self.assertEqual(best["doi"], "10.1000/good")
        self.assertGreaterEqual(best["match_score"], 0.8)

    def test_rejects_weak_title_match(self):
        from ingest.title_metadata_repair import TitleMetadataRepairClient

        client = TitleMetadataRepairClient.__new__(TitleMetadataRepairClient)
        best = client.best_match(
            title="Environmental stress and cognition",
            author=None,
            year=None,
            candidates=[
                {
                    "title": "Marine ecosystems and coral bleaching",
                    "authors": ["Lee"],
                    "year": 2020,
                    "doi": "10.1000/other",
                    "abstract": "Not related.",
                }
            ],
        )

        self.assertIsNone(best)


if __name__ == "__main__":
    unittest.main()
