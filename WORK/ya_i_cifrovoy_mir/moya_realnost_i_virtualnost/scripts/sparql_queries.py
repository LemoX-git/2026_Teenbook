from textwrap import dedent

"""
SPARQL-запросы для темы: Моя реальность/виртуальность

Как использовать:
1. Открыть Wikidata Query Service.
2. Скопировать один из запросов ниже.
3. При необходимости уточнить seed-метки или заменить их на QID.
4. Сохранить реальную выгрузку в папку data/.

Фокусные свойства/отношения: instance of, subclass of, part of, has effect, practiced by
"""

SEED_LABELS = [
    "virtual community",
    "social network",
    "online identity",
    "fear of missing out",
    "interpersonal relationship",
]

QUERY_FIND_BY_LABEL = dedent("""
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?item ?itemLabel ?label WHERE {
  VALUES ?label {
    "virtual community"@en
    "social network"@en
    "online identity"@en
    "fear of missing out"@en
    "interpersonal relationship"@en
  }
  ?item rdfs:label ?label .
  FILTER(LANG(?label) = "en")
  SERVICE wikibase:label { bd:serviceParam wikibase:language "ru,en". }
}
LIMIT 100
""")

QUERY_EXPAND_CLASS_TREE = dedent("""
SELECT DISTINCT ?seed ?seedLabel ?related ?relatedLabel ?relation WHERE {
  VALUES ?seedLabel {
    "virtual community"@en
    "social network"@en
    "online identity"@en
    "fear of missing out"@en
    "interpersonal relationship"@en
  }
  ?seed rdfs:label ?seedLabel .
  FILTER(LANG(?seedLabel) = "en")

  {
    ?related wdt:P31 ?seed .
    BIND("instance of" AS ?relation)
  }
  UNION
  {
    ?related wdt:P279 ?seed .
    BIND("subclass of" AS ?relation)
  }

  SERVICE wikibase:label { bd:serviceParam wikibase:language "ru,en". }
}
LIMIT 150
""")

QUERY_LOCAL_GRAPH = dedent("""
# Локальный граф по seed-понятиям.
SELECT DISTINCT ?item1 ?item1Label ?p ?propLabel ?item2 ?item2Label WHERE {
  VALUES ?startLabel {
    "virtual community"@en
    "social network"@en
    "online identity"@en
    "fear of missing out"@en
    "interpersonal relationship"@en
  }
  ?item1 rdfs:label ?startLabel .
  FILTER(LANG(?startLabel) = "en")
  ?item1 ?p ?item2 .
  FILTER(STRSTARTS(STR(?item2), "http://www.wikidata.org/entity/"))
  ?prop wikibase:directClaim ?p .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "ru,en". }
  BIND(?propLabel AS ?propLabel)
}
LIMIT 200
""")

QUERY_REVERSE_GRAPH = dedent("""
# Кто ссылается на найденные сущности.
SELECT DISTINCT ?item1 ?item1Label ?p ?propLabel ?item2 ?item2Label WHERE {
  VALUES ?targetLabel {
    "virtual community"@en
    "social network"@en
    "online identity"@en
    "fear of missing out"@en
    "interpersonal relationship"@en
  }
  ?item2 rdfs:label ?targetLabel .
  FILTER(LANG(?targetLabel) = "en")
  ?item1 ?p ?item2 .
  FILTER(STRSTARTS(STR(?item1), "http://www.wikidata.org/entity/"))
  ?prop wikibase:directClaim ?p .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "ru,en". }
  BIND(?propLabel AS ?propLabel)
}
LIMIT 200
""")


if __name__ == "__main__":
    for name in [
        "QUERY_FIND_BY_LABEL",
        "QUERY_EXPAND_CLASS_TREE",
        "QUERY_LOCAL_GRAPH",
        "QUERY_REVERSE_GRAPH",
    ]:
        print(f"=== {name} ===")
        print(globals()[name])
        print()
