from app.models import Project


def build_pubmed_query(project: Project) -> tuple[str, str]:
    terms = [project.research_question]
    if project.pico_population:
        terms.append(project.pico_population)
    if project.pico_intervention:
        terms.append(project.pico_intervention)
    if project.pico_outcome:
        terms.append(project.pico_outcome)

    cleaned_terms = [term.strip() for term in terms if term and term.strip()]
    query_text = " AND ".join(f'("{term}"[Title/Abstract])' for term in cleaned_terms)
    rationale = "Generated from research question and available PICO fields."
    return query_text, rationale
