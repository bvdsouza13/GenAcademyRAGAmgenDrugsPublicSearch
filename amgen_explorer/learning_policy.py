"""Conservative deterministic learning routes and vetted source-reading prompts.

Finite rules are a defensive gate, not an exhaustive natural-language safety
classifier. Generated claims still require quotation and independent entailment.
"""
from dataclasses import dataclass
import re

PERSONAL_REASON = "I can explain the label, but an individual treatment or dose decision needs your clinician or pharmacist. Ask about the label's general uses, mechanism or warnings."

@dataclass(frozen=True)
class LearningRoute:
    kind: str
    reason: str = ''
    intent: str = 'general'


def learning_intent(question):
    value = question.lower()
    if re.search(r'overview|essential|introduction', value): return 'overview'
    if re.search(r'warning|contraindicat|side effect|safe|safety|risk|precaution', value): return 'safety'
    if re.search(r'mechanism|how .*work\b|how .*works\b', value): return 'mechanism'
    if re.search(r'indication|approved use|uses|usage', value): return 'indications'
    if re.search(r'teach|learn', value): return 'overview'
    return 'general'


def route_learning_question(question: str, history=None) -> LearningRoute:
    value = str(question).lower().strip()
    intent = learning_intent(value)
    if not value:
        return LearningRoute('clarification', 'Ask a question about the selected medicine’s source label.', intent)
    if re.search(r'\b(compare|versus|vs\.?|better than|interchangeab\w*|switch (?:from|to))\b', value):
        return LearningRoute('unsupported', 'Choose one medicine to learn from its sources. This library teaches each medicine separately and does not establish interchangeability or treatment superiority.', intent)
    if re.search(r'\b(invent|fabricate|fake)\b.*\b(citation|source|reference)\b', value):
        return LearningRoute('unsupported', 'I can only cite reviewed passages supplied by this library. Ask a source-supported question about the selected medicine.', intent)
    if re.search(r'\b(price|cost|stock price|weather|coupon|insurance)\b', value):
        return LearningRoute('unsupported', 'That information is outside this prescribing-information library. Ask about the selected medicine’s label or source passages.', intent)
    learner_only = re.sub(r'help me (?:understand|learn|read)|i (?:want|would like) to (?:learn|understand|read)|explain to me', '', value)
    person = re.search(r'\b(i|my|me|he|she|his|her|him|they|their|child|mother|father|wife|husband)\b|\bpatient\b(?!\s+populations?\b)|\b\d+[ -](?:year[ -]old|years old)\b', learner_only)
    decision = re.search(r'\b(dose|dosage|take|stop|start|switch|treat|prescrib|increase|decrease|recommend|appropriate|suitable|begin)\w*|\buse\b|safe for|okay for', value)
    # "Help me understand" and general source questions keep educational access.
    if ((person and decision) or re.search(r'\bwhat about (me|him|her|my child)\b', value)
            or (person and re.search(r'\b(pregnant|breastfeeding)\b', value) and re.search(r'\b(can|could|should|would|safe|okay)\b', value))):
        return LearningRoute('personal_treatment', PERSONAL_REASON, intent)
    return LearningRoute('educational', intent=intent)


def suggest_followups(assessment, intent) -> list[str]:
    if not assessment.generation_eligible:
        return ['Help me read this source section.'] if assessment.sources else []
    prompts = ['Help me read this source section.']
    for kind, prompt in (
        ('mechanism', 'Explain the mechanism of action in this source.'),
        ('indications', 'What approved uses and limitations does this source describe?'),
        ('safety', 'What warnings and precautions does this source describe?'),
    ):
        if kind in assessment.section_kinds:
            prompts.append(prompt)
    return prompts[:3]
