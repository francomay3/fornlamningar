# K-samsök API Documentation

## Getting Started

On this page you will find code, tips, and examples to help you quickly get started and begin using the K-samsök API!

**Additional Resources:**
- More examples can be found here
- Complete documentation for K-samsök web API can be found here
- Upcoming changes to K-samsök API and protocols are announced here

## Table of Contents

- [Object URIs vs API Calls](#object-uris-vs-api-calls)
- [Response Formats](#response-formats)
- [Response Structure & Examples](#response-structure--examples)
- [Simple Search](#simple-search)
- [Finding Images](#finding-images)
- [Finding Links Between Objects](#finding-links-between-objects)
- [UGC Links](#ugc-links)
- [Geographic Search](#geographic-search)
- [Examples](#examples)
- [Data Freshness](#data-freshness)
- [Code Examples](#code-examples)
- [Frameworks](#frameworks)

## Object URIs vs API Calls

Objects in K-samsök use URIs as persistent identifiers. The URIs are resolvable and respond with data about the object in RDF/XML format:

```
http://kulturarvsdata.se/raa/fmi/10240200820001
```

Unlike searches on `https://kulturarvsdata.se/ksamsok/api...` etc., dereferencing a K-samsök URI on kulturarvsdata.se does not use the K-samsök API.

## Response Formats

### XML & JSON, RDF/XML & JSON-LD

If nothing else is specified, K-samsök URIs respond with RDF/XML, and the API responds with XML that has the hit objects' RDF/XML embedded.

A convenient alternative, however, is to get responses from K-samsök in JSON format – specifically JSON-LD, since K-samsök indexes linked data (RDF). Specify `application/json` or `application/json-ld` in the request's http-Accept header to get responses as JSON-LD. This works for both URIs and API calls.

If you specify `recordSchema=xml` as an option in the call and also specify the values for the fields you want included in the response, you can get back clean (i.e., non-RDF) XML; if you also specify `application/json` in the http-Accept header, you get back regular JSON (i.e., not JSON-LD).

## Response Structure & Examples

### JSON-LD Response Structure (Default)

When using `Accept: application/json` header, the API returns JSON-LD format with embedded RDF data:

```json
{
  "result": {
    "totalHits": 11989,
    "records": [
      {
        "record": {
          "@graph": [
            {
              "@id": "http://kulturarvsdata.se/raa/dokumentation/d9f5cfdb-cd0c-46b0-a7d2-af80dfab05ff",
              "@type": "ksam:Entity",
              "ksam:serviceOrganization": {"@value": "RAÄ", "@language": "sv"},
              "ksam:serviceOrganizationFull": "Riksantikvarieämbetet",
              "ksam:itemSuperType": {"@id": "http://kulturarvsdata.se/resurser/EntitySuperType#object"},
              "ksam:itemKeyword": ["Fornlämningar", "Arkeologi"],
              "ksam:itemLabel": {
                "@value": "Inventeringsbokuppslag (2), Runsten 20:1, Runsten 20:2...",
                "@language": "sv"
              },
              "ksam:serviceName": "arkiv-dokument",
              "ksam:ksamsokVersion": "1.11",
              "ksam:url": "https://pub.raa.se/visa/dokumentation/d9f5cfdb-cd0c-46b0-a7d2-af80dfab05ff",
              "ksam:createdDate": "2023-03-22",
              "ksam:thumbnail": "https://pub.raa.se/dokumentation/d9f5cfdb-cd0c-46b0-a7d2-af80dfab05ff/original/1/miniatyr",
              "ksam:itemClassName": "Dokument",
              "ksam:itemType": {"@id": "http://kulturarvsdata.se/resurser/EntityType#document"},
              "ksam:itemLicense": {"@id": "http://kulturarvsdata.se/resurser/license#cc0"},
              "ksam:itemLicenseUrl": {"@id": "http://creativecommons.org/publicdomain/zero/1.0/"},
              "ksam:dataQuality": {"@id": "http://kulturarvsdata.se/resurser/DataQuality#raw"},
              "ksam:mediaType": "image/jpeg",
              "ksam:describes": [
                {"@id": "http://kulturarvsdata.se/raa/lamning/3ba09003-b1f2-4d5c-85d0-c575d7090f3e"},
                {"@id": "http://kulturarvsdata.se/raa/lamning/481918b8-f95f-4a8f-b12d-bb445db75d79"}
              ]
            }
          ],
          "@context": {
            "pres": "http://kulturarvsdata.se/presentation#",
            "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
            "ksam": "http://kulturarvsdata.se/ksamsok#"
          }
        },
        "rel:score": {"#text": 6.5362163, "-xmlns:rel": "info:srw/extension/2/relevancy-1.0"}
      }
    ],
    "echo": {
      "method": "search",
      "hitsPerPage": 2,
      "startRecord": 1,
      "query": "text=runsten"
    },
    "version": "1.0"
  }
}
```

### Plain JSON Response Structure

When using `recordSchema=xml` with `Accept: application/json` and specifying fields:

```json
{
  "result": {
    "totalHits": 11989,
    "records": {
      "record": {
        "field": [
          {
            "name": "itemId",
            "content": "http://kulturarvsdata.se/raa/dokumentation/d9f5cfdb-cd0c-46b0-a7d2-af80dfab05ff"
          },
          {
            "name": "itemLabel",
            "content": "Inventeringsbokuppslag (2), Runsten 20:1, Runsten 20:2, Runsten 20:3..."
          },
          {
            "name": "itemType",
            "content": "Dokument"
          },
          {
            "name": "serviceName",
            "content": "arkiv-dokument"
          }
        ],
        "rel:score": {
          "xmlns:rel": "info:srw/extension/2/relevancy-1.0",
          "content": 6.5362163
        }
      }
    },
    "echo": {
      "method": "search",
      "hitsPerPage": 1,
      "recordSchema": "xml",
      "startRecord": 1,
      "query": "text=runsten",
      "fields": ["itemId", "itemLabel", "itemType", "serviceName"]
    },
    "version": 1
  }
}
```

### Relations Response Structure

When using `getRelations` method:

```json
{
  "result": {
    "echo": {
      "method": "getRelations",
      "maxCount": 5,
      "objectId": "raa/lamning/94c328d9-3fdf-4269-b73c-37497f49cc5b",
      "relation": "all",
      "inferSameAs": "yes"
    },
    "relations": {
      "count": 4,
      "relation": [
        {
          "type": "replaces",
          "content": "http://kulturarvsdata.se/raa/fmi/10086000200001"
        },
        {
          "source": "deduced",
          "type": "isDescribedBy",
          "content": "http://kulturarvsdata.se/raa/dokumentation/b389e323-5a2b-4e1f-8d34-184113c23bb2"
        },
        {
          "source": "deduced",
          "type": "isDescribedBy",
          "content": "http://kulturarvsdata.se/raa/dokumentation/f538ddd2-6649-4f93-889f-762504b5cdc5"
        },
        {
          "source": "deduced",
          "type": "isDescribedBy",
          "content": "http://kulturarvsdata.se/raa/dokumentation/d9f5cfdb-cd0c-46b0-a7d2-af80dfab05ff"
        }
      ]
    },
    "version": 1
  }
}
```

### UGC API Response Structure

The UGC (User Generated Content) API returns a different format:

```json
{
  "response": {
    "apiVersion": "1.0",
    "relations": [
      {
        "relationType": "sameAs",
        "id": 25383323,
        "userName": "Albin Larsson",
        "relatedUri": "http://www.wikidata.org/entity/Q29408423",
        "applicationName": "Albin Larsson 1",
        "createDate": "2018-10-06"
      }
    ]
  }
}
```

### Error Response Structure

When an error occurs:

```json
{
  "result": {
    "error": "Okänt sökfält: inspireid",
    "version": 1
  }
}
```

Or when required parameters are missing:

```json
{
  "result": {
    "error": "Parametern fields saknas eller är tom",
    "version": 1
  }
}
```

### Key Response Properties

#### JSON-LD Response Properties:
- **`result.totalHits`**: Total number of matching records
- **`result.records`**: Array of record objects
- **`result.echo`**: Echo of the request parameters
- **`result.version`**: API version
- **`record.@graph`**: Array of RDF entities with properties:
  - **`ksam:itemLabel`**: Human-readable label
  - **`ksam:serviceName`**: Service identifier (e.g., "arkiv-dokument")
  - **`ksam:itemType`**: Type of object
  - **`ksam:url`**: Direct link to the object
  - **`ksam:createdDate`**: Creation date (YYYY-MM-DD)
  - **`ksam:thumbnail`**: URL to thumbnail image
  - **`ksam:describes`**: Array of related object URIs
  - **`ksam:itemKeyword`**: Array of keywords/tags

#### Plain JSON Response Properties:
- **`result.totalHits`**: Total number of matching records
- **`result.records.record.field`**: Array of field objects with:
  - **`name`**: Field name
  - **`content`**: Field value
- **`rel:score`**: Relevance score for the result

#### Relations Response Properties:
- **`result.relations.count`**: Number of relations found
- **`result.relations.relation`**: Array of relation objects with:
  - **`type`**: Type of relation (e.g., "isDescribedBy", "replaces")
  - **`content`**: URI of related object
  - **`source`**: Source of relation (e.g., "deduced")

## Simple Search

To perform a simple text search for the string "runsten", you can call the API with the search method and an appropriate query string on text:

```bash
https://kulturarvsdata.se/ksamsok/api?method=search&version=1.1&hitsPerPage=500&query=text=runsten
```

**Note:** In this example, we only get the first 500 results; to see the next 500 on the next "page", we must specify a startRecord: `&startRecord=501`.

If you want to search in specific fields, you can change the generic `query=text=…` to the field you want to search in, e.g., `query=item=yxa`. A complete list of the fields you can search/filter in can be found here.

You can combine search conditions with "and", "or", "not", etc. according to the CQL standard:

```bash
query=item="sten yxa" AND place=gotland NOT itemMaterial=brons
```

## Finding Images

To find objects (of any type) that have embedded images, you can use the `thumbnailExists` parameter (y/n):

```bash
https://kulturarvsdata.se/ksamsok/api?method=search&version=1.1&hitsPerPage=500&query=text=runsten%20AND%20thumbnailExists=j%20AND%20serviceName=kmb
```

## Finding Links Between Objects

There are often links between objects in K-samsök, primarily between physical things – remains, artifacts, etc. – and images that depict them, books that describe them, etc. There are also other types of links, e.g., between people and objects they have owned, events they were present at, etc.

To find such links, you use the `getRelations` method together with the last part of the object's URI as `objectId`:

```bash
https://kulturarvsdata.se/ksamsok/api?method=getRelations&version=1.1&relation=all&maxCount=1000&inferSameAs=yes&objectId=raa/fmi/10048200010001
```

If you want to limit the search to only one type of link, you specify it in the `relation` parameter. In this example, we want to find other objects (probably images) that depict the object in question:

```bash
https://kulturarvsdata.se/ksamsok/api?method=getRelations&version=1.1&relation=isVisualizedBy&maxCount=1000&inferSameAs=yes&objectId=raa/fmi/10048200010001
```

## UGC Links

Alongside K-samsök, there is also a UGC hub where users can contribute their own links, primarily through Kringla. In the UGC hub, there are several links that connect objects within K-samsök, but also links that connect K-samsök objects with external resources. Here you find relations to:

- Articles on Wikipedia
- Images on Wikimedia Commons
- Objects in Europeana
- Bibliographic records at the Royal Library's Libris service

The UGC hub has its own API, which differs slightly from K-samsök's. Here's how you search for UGC links connected to an object:

```bash
https://ugc.kulturarvsdata.se/UGC-hub/api?x-api=ex2147ap36&method=retrieve&scope=all&maxCount=25&objectUri=http://kulturarvsdata.se/raa/fmi/10240200820001
```

Responses are delivered by default in XML format; if JSON format is desired, add `&format=json` to the query string:

```bash
https://ugc.kulturarvsdata.se/UGC-hub/api?x-api=ex2147ap36&method=retrieve&scope=all&maxCount=25&format=json&objectUri=http://kulturarvsdata.se/raa/fmi/10240200820001
```

## Geographic Search

K-samsök's API supports geographic searches with any coordinate system. The search index `boundingBox` limits the search to a rectangular area where two opposite corners are specified with coordinates. Constants exist for certain common coordinate systems (RT90, SWEREF99, WGS84) and others can be specified according to EPSG:xxxx.

### Examples:

**WGS84 coordinates:**
```bash
https://kulturarvsdata.se/ksamsok/api?&method=search&version=1.1&hitsPerPage=25&query=boundingBox=/WGS84%20%2212.883397%2055.56512%2013.01874%2055.635582%22
```

**SWEREF99 coordinates with text filter:**
```bash
https://kulturarvsdata.se/ksamsok/api?method=search&version=1.1&hitsPerPage=25&query=boundingBox=/SWEREF99%20%22366524.557%206159714.112%20375281.959%206167302.335%22%20AND%20text=grav
```

## Examples

Here are some example searches that should show how the search API works.

### Finding All Building Monuments in a Municipality

Here we search for all objects of `itemTyp` building, which have text describing them as state or ecclesiastical building or cultural monuments, but which are not revoked as such, and which are located in Tomelilla municipality, Skåne:

```bash
https://kulturarvsdata.se/ksamsok/api?method=search&version=1.1&hitsPerPage=500&query=text=%22statligt%20byggnadsminne%22%20OR%20%22statligt%20kulturminne%22%20OR%20%22kyrkligt%20byggnadsminne%22%20OR%20%22kyrkligt%20kulturminne%22%20NOT%20%22h%C3%A4vt%22%20AND%20itemType=byggnad%20AND%20municipality=1270
```

**Note:** We have specified Tomelilla municipality with its municipality code, 1270, on the `municipality` attribute. If you don't know all the country's municipality codes by heart, you can alternatively specify the municipality's name with the `municipalityName` attribute, but in that case it might be good to also specify other geographic limitations such as county, for safety's sake.

We could, for example, replace `…AND%20municipality=1270` from the example above with `…AND%20countyName=Sk%C3%A5ne%20AND%20municipalityName=Tomelilla`.

## Data Freshness

K-samsök objects can have several date fields; all use the YYYY-MM-DD format according to ISO 8601. To know when an object was last updated, you should check the `lastChangedDate` field.

Other fields that may be relevant are:
- `addedToIndexDate` - when the object was last harvested to K-samsök
- `createdDate` - when the object record was first created
- `buildDate` - time when the object information was generated

## Code Examples

Trivial examples of how to call the API and interpret the responses can be found in Bash and Perl here. The Bash example, which uses XMLStarlet, is short and simple enough to reproduce here in its entirety:

```bash
#!/usr/bin/env bash

# Search K-samsök using XML tools:
function query() {
	echo "Enter search term:"
	read query
	echo "Number of results (max 500)?"
	read number
	curl -s -g "https://kulturarvsdata.se/ksamsok/api?method=search&version=1.1&hitsPerPage=$number&query=text=$query" \
		| xml sel -N pres="http://kulturarvsdata.se/presentation#" -N ns5="http://kulturarvsdata.se/ksamsok#" -N rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" --template --match "/result/records/record/rdf:RDF/rdf:Description/ns5:presentation/pres:item" --sort A:T:- "pres:organization" -v "concat(pres:organization,'            ',pres:id,'            ',pres:type,'            ',pres:entityUri)" --nl \
		| grep -v '^$' \
		| sed -E 's!/(object|media|fmi)/!/\1/html/!g'
}

query
```

### Python Example with Response Parsing

```python
import requests
import json

def search_ksamsok(query, hits_per_page=10):
    """Search K-samsök API and parse JSON-LD response."""
    url = "https://kulturarvsdata.se/ksamsok/api"
    params = {
        "method": "search",
        "version": "1.1",
        "hitsPerPage": hits_per_page,
        "query": f"text={query}"
    }
    headers = {"Accept": "application/json"}
    
    response = requests.get(url, params=params, headers=headers)
    response.raise_for_status()
    
    data = response.json()
    
    # Extract basic information
    total_hits = data["result"]["totalHits"]
    records = data["result"]["records"]
    
    print(f"Found {total_hits} results")
    
    # Parse each record
    for record in records:
        # Get the main entity from @graph
        entity = record["record"]["@graph"][0]
        
        # Extract key properties
        item_label = entity.get("ksam:itemLabel", {}).get("@value", "No label")
        service_name = entity.get("ksam:serviceName", "Unknown service")
        item_type = entity.get("ksam:itemType", {}).get("@id", "Unknown type")
        url = entity.get("ksam:url", "No URL")
        
        print(f"Label: {item_label}")
        print(f"Service: {service_name}")
        print(f"Type: {item_type}")
        print(f"URL: {url}")
        print("-" * 50)

# Example usage
search_ksamsok("runsten", 3)
```

### Plain JSON Example

```python
def search_ksamsok_simple(query, fields=None):
    """Search K-samsök API with plain JSON response."""
    if fields is None:
        fields = ["itemId", "itemLabel", "itemType", "serviceName"]
    
    url = "https://kulturarvsdata.se/ksamsok/api"
    params = {
        "method": "search",
        "version": "1.1",
        "hitsPerPage": 5,
        "recordSchema": "xml",
        "fields": ",".join(fields),
        "query": f"text={query}"
    }
    headers = {"Accept": "application/json"}
    
    response = requests.get(url, params=params, headers=headers)
    response.raise_for_status()
    
    data = response.json()
    
    # Parse simple field structure
    record = data["result"]["records"]["record"]
    for field in record["field"]:
        print(f"{field['name']}: {field['content']}")

# Example usage
search_ksamsok_simple("runsten")
```

## Frameworks

Albin Larsson has written frameworks for interacting with K-samsök for Python and PHP. He has also created a layer on top of the API that provides a more REST-like interface. There are also tools for easily downloading posts from a search query's hit list, or entire datasets, and importing them into a triplestore as RDF.