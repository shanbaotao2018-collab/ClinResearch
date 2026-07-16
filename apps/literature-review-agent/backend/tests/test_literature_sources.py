from xml.etree import ElementTree

from app.services.literature_sources import (
    normalize_europepmc_record,
    normalize_pubmed_article,
)


def test_normalize_pubmed_article_extracts_core_fields():
    xml = """
    <PubmedArticle>
      <MedlineCitation>
        <PMID>123456</PMID>
        <Article>
          <ArticleTitle>Effect of SGLT2 inhibitors on heart failure</ArticleTitle>
          <Abstract>
            <AbstractText Label="Background">Cardiovascular outcomes are important.</AbstractText>
            <AbstractText Label="Results">Hospitalization risk was reduced.</AbstractText>
          </Abstract>
          <AuthorList>
            <Author>
              <LastName>Zinman</LastName>
              <Initials>B</Initials>
            </Author>
            <Author>
              <LastName>Wanner</LastName>
              <Initials>C</Initials>
            </Author>
          </AuthorList>
          <Journal>
            <Title>New England Journal of Medicine</Title>
            <JournalIssue>
              <PubDate>
                <Year>2015</Year>
              </PubDate>
            </JournalIssue>
          </Journal>
        </Article>
      </MedlineCitation>
      <PubmedData>
        <ArticleIdList>
          <ArticleId IdType="doi">10.1056/NEJMoa1504720</ArticleId>
        </ArticleIdList>
      </PubmedData>
    </PubmedArticle>
    """
    article = ElementTree.fromstring(xml)

    normalized = normalize_pubmed_article(article)

    assert normalized["external_id"] == "123456"
    assert normalized["title"] == "Effect of SGLT2 inhibitors on heart failure"
    assert "Background:" in normalized["abstract"]
    assert normalized["authors"] == "Zinman B; Wanner C"
    assert normalized["publication_year"] == 2015
    assert normalized["doi"] == "10.1056/NEJMoa1504720"


def test_normalize_europepmc_record_extracts_core_fields():
    record = {
        "id": "PPR123",
        "pmid": "30000001",
        "title": "Dapagliflozin and cardiovascular outcomes",
        "abstractText": "A randomized clinical trial.",
        "authorString": "Wiviott SD; Raz I",
        "pubYear": "2019",
        "doi": "10.1056/NEJMoa1812389",
        "journalTitle": "N Engl J Med",
        "pmcid": "PMC0000001",
    }

    normalized = normalize_europepmc_record(record)

    assert normalized["external_id"] == "30000001"
    assert normalized["title"] == "Dapagliflozin and cardiovascular outcomes"
    assert normalized["authors"] == "Wiviott SD; Raz I"
    assert normalized["publication_year"] == 2019
    assert normalized["doi"] == "10.1056/NEJMoa1812389"
    assert normalized["pmcid"] == "PMC0000001"
