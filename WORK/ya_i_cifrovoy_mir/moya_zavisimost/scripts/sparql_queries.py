from textwrap import dedent


SEED_LABELS = [
    "screen time",
    "smartphone",
    "sleep",
    "attention",
    "digital detox",
    "social media",
]

QUERY_FIND_BY_LABEL = dedent("""
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?item ?itemLabel ?label WHERE {
  VALUES ?label {
    "screen time"@en
    "smartphone"@en
    "sleep"@en
    "attention"@en
    "digital detox"@en
    "social media"@en
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
    "screen time"@en
    "smartphone"@en
    "sleep"@en
    "attention"@en
    "digital detox"@en
    "social media"@en
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
    "screen time"@en
    "smartphone"@en
    "sleep"@en
    "attention"@en
    "digital detox"@en
    "social media"@en
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
    "screen time"@en
    "smartphone"@en
    "sleep"@en
    "attention"@en
    "digital detox"@en
    "social media"@en
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
