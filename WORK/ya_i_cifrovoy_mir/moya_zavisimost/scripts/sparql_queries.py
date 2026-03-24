from textwrap import dedent

# Черновые SPARQL-запросы для темы: Моя зависимость
# При желании запросы можно запускать через SPARQLWrapper или прямо в Wikidata Query Service.

QUERY_LABEL_SEARCH = dedent("""
SELECT ?item ?itemLabel WHERE {
  VALUES ?label { "screen time"@en "smartphone"@en "sleep"@en }
  ?item rdfs:label ?label .
  FILTER(LANG(?label) = "en")
  SERVICE wikibase:label { bd:serviceParam wikibase:language "ru,en". }
}
LIMIT 50
""")

QUERY_SUBCLASSES_AND_INSTANCEOF = dedent("""
SELECT ?seed ?seedLabel ?related ?relatedLabel ?relationLabel WHERE {
  VALUES ?seedLabel {
    "screen time"@en
    "smartphone"@en
    "sleep"@en
    "attention"@en
    "digital detox"@en
  }
  ?seed rdfs:label ?seedLabel .
  FILTER(LANG(?seedLabel) = "en")

  {
    ?related wdt:P31 ?seed .
    BIND("instance of"@en AS ?relationLabel)
  }
  UNION
  {
    ?related wdt:P279 ?seed .
    BIND("subclass of"@en AS ?relationLabel)
  }

  SERVICE wikibase:label { bd:serviceParam wikibase:language "ru,en". }
}
LIMIT 100
""")

QUERY_SIMPLE_GRAPH = dedent("""
# Шаблон графового запроса по мотивам примера из методички.
SELECT DISTINCT ?item1 ?item1Label ?item2 ?item2Label WHERE {
  VALUES ?startLabel {
    "screen time"@en
    "smartphone"@en
  }
  ?start rdfs:label ?startLabel .
  FILTER(LANG(?startLabel) = "en")
  VALUES ?item1 { ?start }
  ?item1 ?p ?item2 .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "ru,en". }
}
LIMIT 80
""")

if __name__ == "__main__":
    print("=== QUERY_LABEL_SEARCH ===")
    print(QUERY_LABEL_SEARCH)
    print() 
    print("=== QUERY_SUBCLASSES_AND_INSTANCEOF ===")
    print(QUERY_SUBCLASSES_AND_INSTANCEOF)
    print() 
    print("=== QUERY_SIMPLE_GRAPH ===")
    print(QUERY_SIMPLE_GRAPH)
