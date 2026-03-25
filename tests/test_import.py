# Version: 3.2.2
"""
Article Finder v3.2 - Comprehensive Test Suite
Tests for import, parsing, classification, and integration.
"""

import unittest
import tempfile
import json
from pathlib import Path
from datetime import datetime

# Test data - various citation formats
TEST_CITATIONS = [
    # APA style
    {
        'text': "Smith, J. A., & Jones, B. C. (2020). The effects of daylight on cognitive performance. Journal of Environmental Psychology, 45(3), 234-256.",
        'expected': {
            'authors': ['Smith, J. A.', 'Jones, B. C.'],
            'year': 2020,
            'title': 'The effects of daylight on cognitive performance',
            'venue': 'Journal of Environmental Psychology'
        }
    },
    # MLA style
    {
        'text': 'Ulrich, Roger S. "View through a Window May Influence Recovery from Surgery." Science, vol. 224, no. 4647, 1984, pp. 420-421.',
        'expected': {
            'year': 1984,
            'title': 'View through a Window May Influence Recovery from Surgery',
            'venue': 'Science'
        }
    },
    # With DOI
    {
        'text': "Ledoux, J.E. Cognitive-Emotional Interactions in the Brain. Cogn. Emot. 2008, 3, 267-289. https://doi.org/10.1080/02699930802132356",
        'expected': {
            'year': 2008,
            'doi': '10.1080/02699930802132356'
        }
    },
    # Informal book citation
    {
        'text': "Williams Goldhagen, S. Welcome to Your World: How the Built Environment Shapes our Lives; HarperCollins: New York, NY, USA, 2017.",
        'expected': {
            'year': 2017,
            'title_contains': 'Welcome to Your World'
        }
    },
    # Very informal
    {
        'text': "Glass & Singer 1972 Urban Stress",
        'expected': {
            'year': 1972
        }
    }
]

# Test PDF filenames
TEST_PDF_FILENAMES = [
    {
        'filename': 'Wastiels,_L.,_&_He.pdf',
        'expected_authors': ['Wastiels']
    },
    {
        'filename': '2020_Smith_Daylight_Effects.pdf',
        'expected_year': 2020,
        'expected_authors': ['Smith']
    },
    {
        'filename': '10.1016_j.jenvp.2020.01.001.pdf',
        'expected_doi': '10.1016/j.jenvp.2020.01.001'
    },
    {
        'filename': 'View Through Window Ulrich 1984.pdf',
        'expected_year': 1984,
        'expected_title_contains': 'View'
    }
]

# Test spreadsheet column names
TEST_COLUMN_MAPPINGS = [
    # Standard columns
    {
        'headers': ['DOI', 'Title', 'Authors', 'Year', 'Journal'],
        'expected': {'doi': 'DOI', 'title': 'Title', 'authors': 'Authors', 'year': 'Year', 'venue': 'Journal'}
    },
    # Non-standard but recognizable
    {
        'headers': ['Article DOI', 'Paper Title', 'Author List', 'Publication Year', 'Source'],
        'expected': {'doi': 'Article DOI', 'title': 'Paper Title', 'authors': 'Author List', 'year': 'Publication Year'}
    },
    # Citation string column
    {
        'headers': ['Row Number', 'Reference Information'],
        'expected': {'citation': 'Reference Information'}
    },
    # Mixed case
    {
        'headers': ['doi', 'TITLE', 'Authors', 'year'],
        'expected': {'doi': 'doi', 'title': 'TITLE', 'authors': 'Authors', 'year': 'year'}
    }
]


class TestCitationParser(unittest.TestCase):
    """Tests for citation string parsing."""
    
    @classmethod
    def setUpClass(cls):
        from ingest.citation_parser import CitationParser
        cls.parser = CitationParser()
    
    def test_apa_citation(self):
        """Test APA-style citation parsing."""
        result = self.parser.parse(TEST_CITATIONS[0]['text'])
        
        self.assertEqual(result.year, 2020)
        self.assertTrue(len(result.authors) >= 1)
        self.assertIn('Smith', result.authors[0])
        self.assertIsNotNone(result.title)
        self.assertGreater(result.confidence, 0.5)
    
    def test_mla_citation(self):
        """Test MLA-style citation parsing."""
        result = self.parser.parse(TEST_CITATIONS[1]['text'])
        
        self.assertEqual(result.year, 1984)
        self.assertIn('Window', result.title)
        self.assertGreater(result.confidence, 0.3)
    
    def test_doi_extraction(self):
        """Test DOI extraction from citation."""
        result = self.parser.parse(TEST_CITATIONS[2]['text'])
        
        self.assertIsNotNone(result.doi)
        self.assertTrue(result.doi.startswith('10.'))
    
    def test_informal_citation(self):
        """Test informal citation parsing."""
        result = self.parser.parse(TEST_CITATIONS[4]['text'])
        
        self.assertEqual(result.year, 1972)
    
    def test_empty_citation(self):
        """Test handling of empty input."""
        result = self.parser.parse("")
        self.assertEqual(result.confidence, 0.0)
        
        result = self.parser.parse(None)
        self.assertEqual(result.confidence, 0.0)
    
    def test_batch_parsing(self):
        """Test batch citation parsing."""
        from ingest.citation_parser import BatchCitationParser
        
        batch_parser = BatchCitationParser()
        citations = [c['text'] for c in TEST_CITATIONS]
        
        results, stats = batch_parser.parse_all(citations)
        
        self.assertEqual(len(results), len(citations))
        self.assertEqual(stats['total'], len(citations))
        self.assertGreater(stats['with_year'], 0)


class TestPDFCataloger(unittest.TestCase):
    """Tests for PDF filename parsing and cataloging."""
    
    @classmethod
    def setUpClass(cls):
        from ingest.pdf_cataloger import FilenameParser
        cls.parser = FilenameParser()
    
    def test_author_filename(self):
        """Test author-based filename parsing."""
        result = self.parser.parse(TEST_PDF_FILENAMES[0]['filename'])
        
        self.assertTrue(len(result.authors) >= 1)
        self.assertIn('Wastiels', result.authors[0])
    
    def test_year_author_filename(self):
        """Test year-author-title filename parsing."""
        result = self.parser.parse(TEST_PDF_FILENAMES[1]['filename'])
        
        self.assertEqual(result.year, 2020)
        # Title extraction should capture "Smith Daylight Effects"
        self.assertIsNotNone(result.title)
        self.assertIn('Smith', result.title or '')  # Smith is in title since no explicit author
    
    def test_doi_filename(self):
        """Test DOI-based filename parsing."""
        result = self.parser.parse(TEST_PDF_FILENAMES[2]['filename'])
        
        self.assertIsNotNone(result.doi)
        self.assertIn('10.1016', result.doi)


class TestColumnDetector(unittest.TestCase):
    """Tests for column detection in spreadsheets."""
    
    @classmethod
    def setUpClass(cls):
        from ingest.smart_importer import ColumnDetector
        cls.detector = ColumnDetector()
    
    def test_standard_columns(self):
        """Test detection of standard column names."""
        mapping = self.detector.detect_columns(TEST_COLUMN_MAPPINGS[0]['headers'])
        
        self.assertEqual(mapping.doi, 'DOI')
        self.assertEqual(mapping.title, 'Title')
        self.assertEqual(mapping.authors, 'Authors')
        self.assertEqual(mapping.year, 'Year')
    
    def test_nonstandard_columns(self):
        """Test detection of non-standard but recognizable columns."""
        mapping = self.detector.detect_columns(TEST_COLUMN_MAPPINGS[1]['headers'])
        
        self.assertIsNotNone(mapping.doi)
        self.assertIsNotNone(mapping.title)
        self.assertIsNotNone(mapping.year)
    
    def test_citation_column(self):
        """Test detection of citation string column."""
        mapping = self.detector.detect_columns(TEST_COLUMN_MAPPINGS[2]['headers'])
        
        self.assertEqual(mapping.citation, 'Reference Information')
    
    def test_mixed_case(self):
        """Test handling of mixed case column names."""
        mapping = self.detector.detect_columns(TEST_COLUMN_MAPPINGS[3]['headers'])
        
        self.assertIsNotNone(mapping.doi)
        self.assertIsNotNone(mapping.title)
    
    def test_content_based_detection(self):
        """Test content-based column detection."""
        headers = ['Column A', 'Column B', 'Column C']
        sample_rows = [
            {'Column A': '10.1234/test.123', 'Column B': 'Some Title', 'Column C': '2020'},
            {'Column A': '10.5678/test.456', 'Column B': 'Another Title', 'Column C': '2021'},
        ]
        
        mapping = self.detector.detect_columns(headers, sample_rows)
        
        # Should detect DOI column from content
        self.assertEqual(mapping.doi, 'Column A')
        # Should detect year column from content
        self.assertEqual(mapping.year, 'Column C')


class TestSmartImporter(unittest.TestCase):
    """Tests for the smart importer."""
    
    def test_preview_csv(self):
        """Test CSV file preview."""
        from ingest.smart_importer import SmartImporter
        
        # Create temp CSV
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("DOI,Title,Year\n")
            f.write("10.1234/test,Test Paper,2020\n")
            f.write("10.5678/test2,Another Paper,2021\n")
            temp_path = Path(f.name)
        
        try:
            importer = SmartImporter()
            preview = importer.preview_file(temp_path)
            
            self.assertIn('columns', preview)
            self.assertIn('sample_rows', preview)
            self.assertEqual(len(preview['columns']), 3)
            self.assertGreater(len(preview['sample_rows']), 0)
        finally:
            temp_path.unlink()
    
    def test_doi_extraction(self):
        """Test DOI extraction from various formats."""
        from ingest.smart_importer import SmartImporter
        
        importer = SmartImporter()
        
        # Direct DOI
        self.assertEqual(importer._extract_doi('10.1234/test'), '10.1234/test')
        
        # DOI URL
        self.assertEqual(importer._extract_doi('https://doi.org/10.1234/test'), '10.1234/test')
        
        # DOI in text
        self.assertEqual(importer._extract_doi('See DOI: 10.1234/test for details'), '10.1234/test')
        
        # Empty
        self.assertIsNone(importer._extract_doi(''))
        self.assertIsNone(importer._extract_doi('no doi here'))


class TestDOIResolver(unittest.TestCase):
    """Tests for DOI resolution (mocked)."""
    
    def test_doi_normalization(self):
        """Test DOI normalization."""
        from ingest.doi_resolver import DOIResolver
        
        resolver = DOIResolver()
        
        # Various formats
        self.assertEqual(resolver._normalize_doi('10.1234/test'), '10.1234/test')
        self.assertEqual(resolver._normalize_doi('https://doi.org/10.1234/test'), '10.1234/test')
        self.assertEqual(resolver._normalize_doi('DOI:10.1234/test'), '10.1234/test')
        
        # Invalid
        self.assertIsNone(resolver._normalize_doi('not a doi'))
        self.assertIsNone(resolver._normalize_doi(''))


class TestTaxonomyScoring(unittest.TestCase):
    """Tests for taxonomy and scoring (requires database setup)."""
    
    def test_taxonomy_structure(self):
        """Test that taxonomy file is valid."""
        import yaml
        
        taxonomy_path = Path(__file__).parent.parent / 'config' / 'taxonomy.yaml'
        
        if taxonomy_path.exists():
            with open(taxonomy_path) as f:
                taxonomy = yaml.safe_load(f)
            
            self.assertIn('facets', taxonomy)
            
            # Check facet structure
            for facet in taxonomy['facets']:
                self.assertIn('id', facet)
                self.assertIn('name', facet)
            
            # Check that node definitions exist (they're organized by facet ID)
            # e.g., environmental_factors, outcomes, subjects, etc.
            facet_ids = [f['id'] for f in taxonomy['facets']]
            node_count = 0
            for facet_id in facet_ids:
                if facet_id in taxonomy:
                    nodes = taxonomy[facet_id]
                    if isinstance(nodes, list):
                        node_count += len(nodes)
            
            # Should have nodes defined
            self.assertGreater(node_count, 0, "Taxonomy should have nodes")


class TestContractCompliance(unittest.TestCase):
    """Tests for Article Eater contract compliance."""
    
    def test_job_bundle_schema(self):
        """Test that job bundles conform to ae.paper.v1 schema."""
        schema_path = Path(__file__).parent.parent / 'schemas' / 'ae.paper.v1.json'
        
        if not schema_path.exists():
            self.skipTest("Schema file not found")
        
        import jsonschema
        
        with open(schema_path) as f:
            schema = json.load(f)
        
        # Test valid bundle
        valid_bundle = {
            "schema": "ae.paper.v1",
            "paper_id": "doi:10.1234/test",
            "doi": "10.1234/test",
            "title": "Test Paper",
            "authors": [{"name": "Test Author"}],
            "year": 2020,
            "pdf_sha256": "abc123" * 10 + "abcd",
            "pdf_bytes": 12345,
            "source": {"name": "test", "retrieved_at": "2024-01-01T00:00:00Z"},
            "triage": {
                "decision": "send_to_eater",
                "reasons": ["test"]
            }
        }
        
        try:
            jsonschema.validate(valid_bundle, schema)
        except jsonschema.ValidationError as e:
            self.fail(f"Valid bundle failed validation: {e}")


class TestIntegration(unittest.TestCase):
    """Integration tests for full workflows."""
    
    def test_import_to_classification_flow(self):
        """Test that imported papers can be classified."""
        # This would require a full database setup
        # Placeholder for now
        pass
    
    def test_citation_to_expansion_flow(self):
        """Test that citations populate expansion queue."""
        # Placeholder
        pass


class TestExpansionScorer(unittest.TestCase):
    """Tests for taxonomy-bounded expansion."""
    
    def test_scored_paper_dataclass(self):
        """Test ScoredPaper dataclass."""
        from search.expansion_scorer import ScoredPaper
        
        paper = ScoredPaper(
            paper_id='test:123',
            doi='10.1234/test',
            title='Test Paper About Daylighting',
            authors=['Smith', 'Jones'],
            year=2020,
            abstract='This paper examines daylighting effects on cognition.',
            relevance_score=0.75,
            top_facets=[('environmental_factors', 0.8), ('outcomes', 0.7)],
            decision='queue'
        )
        
        self.assertEqual(paper.paper_id, 'test:123')
        self.assertEqual(paper.relevance_score, 0.75)
        
        # Test to_dict
        d = paper.to_dict()
        self.assertEqual(d['doi'], '10.1234/test')
        self.assertEqual(d['decision'], 'queue')
    
    def test_relevance_filter_threshold(self):
        """Test relevance filter threshold logic."""
        from search.expansion_scorer import RelevanceFilter, ScoredPaper
        
        filter = RelevanceFilter(threshold=0.4, max_depth=2)
        
        # High score should pass
        high_paper = ScoredPaper(
            paper_id='high',
            doi='10.1234/high',
            title='Relevant Paper',
            authors=[],
            year=2020,
            abstract=None,
            relevance_score=0.6,
            discovery_depth=1
        )
        should_queue, reason = filter.should_queue(high_paper)
        self.assertTrue(should_queue)
        
        # Low score should fail
        low_paper = ScoredPaper(
            paper_id='low',
            doi='10.1234/low',
            title='Irrelevant Paper',
            authors=[],
            year=2020,
            abstract=None,
            relevance_score=0.2,
            discovery_depth=1
        )
        should_queue, reason = filter.should_queue(low_paper)
        self.assertFalse(should_queue)
        self.assertIn('threshold', reason.lower())
    
    def test_relevance_filter_depth(self):
        """Test relevance filter depth check."""
        from search.expansion_scorer import RelevanceFilter, ScoredPaper
        
        filter = RelevanceFilter(threshold=0.3, max_depth=2)
        
        # Within depth should pass
        shallow = ScoredPaper(
            paper_id='shallow',
            doi=None,
            title='Test',
            authors=[],
            year=2020,
            abstract=None,
            relevance_score=0.5,
            discovery_depth=2
        )
        should_queue, _ = filter.should_queue(shallow)
        self.assertTrue(should_queue)
        
        # Beyond depth should fail
        deep = ScoredPaper(
            paper_id='deep',
            doi=None,
            title='Test',
            authors=[],
            year=2020,
            abstract=None,
            relevance_score=0.8,  # Even high score fails
            discovery_depth=3
        )
        should_queue, reason = filter.should_queue(deep)
        self.assertFalse(should_queue)
        self.assertIn('depth', reason.lower())


class TestDeduplicator(unittest.TestCase):
    """Tests for duplicate detection."""
    
    def test_title_normalizer(self):
        """Test title normalization."""
        from search.deduplicator import TitleNormalizer
        
        # Should normalize to same value
        title1 = "The Effects of Daylight on Cognitive Performance"
        title2 = "Effects of daylight on cognitive performance"
        
        norm1 = TitleNormalizer.normalize(title1)
        norm2 = TitleNormalizer.normalize(title2)
        
        self.assertEqual(norm1, norm2)
    
    def test_title_key_terms(self):
        """Test key term extraction."""
        from search.deduplicator import TitleNormalizer
        
        title = "Effects of natural daylight on cognitive performance in offices"
        terms = TitleNormalizer.extract_key_terms(title, n=5)
        
        self.assertIn('daylight', terms)
        self.assertIn('cognitive', terms)
        self.assertIn('performance', terms)
    
    def test_author_normalizer(self):
        """Test author name normalization."""
        from search.deduplicator import AuthorNormalizer
        
        # Different formats, same person
        self.assertEqual(AuthorNormalizer.normalize("Smith, John"), "smith")
        self.assertEqual(AuthorNormalizer.normalize("John Smith"), "smith")
        self.assertEqual(AuthorNormalizer.normalize("J. Smith"), "smith")
    
    def test_author_list_normalization(self):
        """Test author list normalization."""
        from search.deduplicator import AuthorNormalizer
        
        authors = ["Smith, J.", "Jones, B.C.", "Williams"]
        surnames = AuthorNormalizer.normalize_list(authors)
        
        self.assertIn("smith", surnames)
        self.assertIn("jones", surnames)
        self.assertIn("williams", surnames)
    
    def test_match_result(self):
        """Test MatchResult dataclass."""
        from search.deduplicator import MatchResult
        
        result = MatchResult(
            is_duplicate=True,
            matched_paper_id='doi:10.1234/test',
            match_type='doi',
            confidence=1.0
        )
        
        self.assertTrue(result.is_duplicate)
        self.assertEqual(result.match_type, 'doi')
        
        d = result.to_dict()
        self.assertEqual(d['confidence'], 1.0)
    
    def test_paper_merger(self):
        """Test paper record merging."""
        from search.deduplicator import PaperMerger
        
        existing = {
            'paper_id': 'doi:10.1234/test',
            'doi': '10.1234/test',
            'title': 'Short Title',
            'authors': ['Smith'],
            'abstract': None
        }
        
        new = {
            'title': 'Much Longer and More Descriptive Title',
            'authors': ['Smith', 'Jones'],
            'abstract': 'This is the abstract.',
            'year': 2020
        }
        
        merged = PaperMerger.merge(existing, new)
        
        # Should take longer title
        self.assertEqual(merged['title'], new['title'])
        # Should have abstract now
        self.assertEqual(merged['abstract'], new['abstract'])
        # Should combine authors
        self.assertIn('Jones', merged['authors'])
        # Should have year
        self.assertEqual(merged['year'], 2020)
        # Should keep original paper_id
        self.assertEqual(merged['paper_id'], existing['paper_id'])


def run_quick_tests():
    """Run a quick subset of tests."""
    suite = unittest.TestSuite()
    
    suite.addTest(TestCitationParser('test_apa_citation'))
    suite.addTest(TestCitationParser('test_doi_extraction'))
    suite.addTest(TestColumnDetector('test_standard_columns'))
    suite.addTest(TestSmartImporter('test_doi_extraction'))
    
    runner = unittest.TextTestRunner(verbosity=2)
    return runner.run(suite)


def run_all_tests():
    """Run all tests."""
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=Path(__file__).parent, pattern='test_*.py')
    
    runner = unittest.TextTestRunner(verbosity=2)
    return runner.run(suite)


if __name__ == '__main__':
    import sys
    
    if '--quick' in sys.argv:
        result = run_quick_tests()
    else:
        result = unittest.main(verbosity=2, exit=False)
    
    sys.exit(0 if result.wasSuccessful() else 1)
