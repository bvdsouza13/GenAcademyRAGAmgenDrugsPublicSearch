"""Provider-free query interpretation; recognized names never become filters."""
from __future__ import annotations
from dataclasses import dataclass, field
from difflib import get_close_matches
import re


def tokens(text):
    return re.findall(r'[^\W_]+', text.casefold(), flags=re.UNICODE)


# Negation, numbers, units and source qualifiers deliberately remain meaningful.
FILLER = set('a an the what who which where when why should is are was were do does did can could would you me tell about please give explain describe described supplied label labels medicine medicines drug drugs how of to for in on and or i my we our this that it its with using'.split())
SECTIONS = {'mechanism':('mechanism','action','works','work'),
            'storage':('storage','store','stored','refrigerated','cold','chilled'),
            'warnings':('warning','warnings','precautions','safety','effects'),
            'dosage':('dosage','dose','dosing','mg','mcg'),
            'overview':('overview','summary')}
CONCEPTS = (frozenset(('cold','chilled','refrigerated','refrigerator')),
            frozenset(('work','works','mechanism','action')),
            frozenset(('side','effects','adverse','reactions')))


@dataclass(frozen=True)
class QueryIntent:
    query: str
    meaningful_terms: list[str] = field(default_factory=list)
    product_candidates: list[str] = field(default_factory=list)
    ambiguity: bool = False
    section_intent: str | None = None
    suggestions: list[str] = field(default_factory=list)
    needs_context: bool = False
    alias_terms: list[str] = field(default_factory=list)
    matched_aliases: list[str] = field(default_factory=list)


def analyze_query(query: str, corpus) -> QueryIntent:
    words=tokens(query);normalized=' '+' '.join(words)+' '
    candidates=[];aliases={};alias_terms=[];ambiguous=False;matched_aliases=[]
    for product in corpus.products if corpus is not None else []:
        for alias in (product.name, product.generic_name):
            key=' '.join(tokens(alias))
            if key:aliases.setdefault(key,[]).append(product)
    for alias,products in aliases.items():
        if ' '+alias+' ' in normalized:
            candidates.extend(p.id for p in products)
            alias_terms.extend(alias.split())
            matched_aliases.append(alias)
            ambiguous=ambiguous or len({p.id for p in products})>1
    meaningful=list(dict.fromkeys(w for w in words if w not in FILLER or w in alias_terms))
    section=next((section for section,terms in SECTIONS.items() if any(w in terms for w in words)),None)
    suggestions=[p.name for p in (corpus.products if corpus is not None else []) if ambiguous and p.id in candidates]
    if not candidates:
        for word in meaningful:
            if len(word)<5:continue
            for near in get_close_matches(word,[a for a in aliases if ' ' not in a],n=2,cutoff=.84):
                suggestions.extend(p.name for p in aliases[near])
    context=not candidates and bool(set(words)&{'it','its','that','this'})
    return QueryIntent(query,meaningful,list(dict.fromkeys(candidates)),ambiguous,section,
                       list(dict.fromkeys(suggestions)),context,list(dict.fromkeys(alias_terms)),matched_aliases)
