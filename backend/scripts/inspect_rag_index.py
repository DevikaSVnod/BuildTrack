"""One-off: print RAG index schema and sample document."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient

from app.core.config import settings

c = SearchIndexClient(settings.AZURE_SEARCH_ENDPOINT, AzureKeyCredential(settings.AZURE_SEARCH_KEY))
print("INDEXES:")
for idx in c.list_indexes():
    print(" ", idx.name)

rag_names = [i.name for i in c.list_indexes() if "rag" in i.name.lower()]
print("RAG indexes:", rag_names)
if not rag_names:
    raise SystemExit(0)

name = rag_names[0]
idx = c.get_index(name)
print(f"\nFields in {name}:")
for f in idx.fields:
    print(f"  {f.name}: {f.type}")

sc = SearchClient(settings.AZURE_SEARCH_ENDPOINT, name, AzureKeyCredential(settings.AZURE_SEARCH_KEY))
rows = list(sc.search(search_text="*", top=1, select="*"))
if rows:
    print("\nSample document:")
    for k, v in rows[0].items():
        if k.startswith("@"):
            continue
        if isinstance(v, list) and len(v) > 5:
            print(f"  {k}: list[{len(v)}]")
        else:
            print(f"  {k}: {json.dumps(v, default=str)[:200]}")
