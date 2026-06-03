from typing import List, Dict, Any, Optional
from app.core.config import settings
import json
import logging

logger = logging.getLogger(__name__)

VECTOR_FIELD = "content_vector"
VECTOR_DIM = 1536          # text-embedding-3-small
VECTOR_PROFILE = "buildtrack-hnsw"


def _add_vector(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Embed title + content and add content_vector field in-place."""
    try:
        from app.search.embeddings import embed_text
        text = f"{doc.get('title', '')} {doc.get('content', '')}".strip()
        vector = embed_text(text)
        if vector:
            doc[VECTOR_FIELD] = vector
        else:
            logger.warning(f"No vector for doc {doc.get('id')} — embeddings not configured or call failed")
    except Exception as e:
        logger.warning(f"Vector embedding skipped for {doc.get('id')}: {e}")
    return doc


def get_search_client():
    if not settings.AZURE_SEARCH_ENDPOINT or not settings.AZURE_SEARCH_KEY:
        return None
    try:
        from azure.search.documents import SearchClient
        from azure.core.credentials import AzureKeyCredential
        return SearchClient(
            endpoint=settings.AZURE_SEARCH_ENDPOINT,
            index_name=settings.AZURE_SEARCH_INDEX,
            credential=AzureKeyCredential(settings.AZURE_SEARCH_KEY),
        )
    except Exception as e:
        logger.error(f"Failed to create search client: {e}")
        return None


def get_index_client():
    if not settings.AZURE_SEARCH_ENDPOINT or not settings.AZURE_SEARCH_KEY:
        return None
    try:
        from azure.search.documents.indexes import SearchIndexClient
        from azure.core.credentials import AzureKeyCredential
        return SearchIndexClient(
            endpoint=settings.AZURE_SEARCH_ENDPOINT,
            credential=AzureKeyCredential(settings.AZURE_SEARCH_KEY),
        )
    except Exception as e:
        logger.error(f"Failed to create index client: {e}")
        return None


def ensure_index_exists() -> bool:
    """
    Create the index or add new fields to an existing index.
    Azure does not allow changing attributes on existing fields (e.g. adding facetable).
    Returns True if index is ready.
    """
    client = get_index_client()
    if not client:
        return False
    try:
        from azure.core.exceptions import ResourceNotFoundError
        from azure.search.documents.indexes.models import (
            SearchIndex,
            SearchField,
            SearchFieldDataType,
            SimpleField,
            SearchableField,
            SemanticConfiguration,
            SemanticSearch,
            SemanticPrioritizedFields,
            SemanticField,
            VectorSearch,
            HnswAlgorithmConfiguration,
            VectorSearchProfile,
        )

        filter_fields = [
            SimpleField(name="progress_pct", type=SearchFieldDataType.Int32, filterable=True, sortable=True),
            SimpleField(name="record_status", type=SearchFieldDataType.String, filterable=True),
        ]

        def _full_index() -> SearchIndex:
            fields = [
                SimpleField(name="id", type=SearchFieldDataType.String, key=True),
                SearchableField(name="title", type=SearchFieldDataType.String),
                SearchableField(name="content", type=SearchFieldDataType.String),
                SimpleField(name="content_type", type=SearchFieldDataType.String, filterable=True),
                SimpleField(name="url", type=SearchFieldDataType.String, retrievable=True),
                SimpleField(name="metadata", type=SearchFieldDataType.String, retrievable=True),
                *filter_fields,
                SearchField(
                    name=VECTOR_FIELD,
                    type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                    searchable=True,
                    vector_search_dimensions=VECTOR_DIM,
                    vector_search_profile_name=VECTOR_PROFILE,
                ),
            ]
            semantic_config = SemanticConfiguration(
                name="default",
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="title"),
                    content_fields=[SemanticField(field_name="content")],
                ),
            )
            vector_search = VectorSearch(
                algorithms=[HnswAlgorithmConfiguration(name="buildtrack-hnsw-algo")],
                profiles=[VectorSearchProfile(
                    name=VECTOR_PROFILE,
                    algorithm_configuration_name="buildtrack-hnsw-algo",
                )],
            )
            return SearchIndex(
                name=settings.AZURE_SEARCH_INDEX,
                fields=fields,
                semantic_search=SemanticSearch(configurations=[semantic_config]),
                vector_search=vector_search,
            )

        try:
            existing = client.get_index(settings.AZURE_SEARCH_INDEX)
            names = {f.name for f in existing.fields}
            added = [f.name for f in filter_fields if f.name not in names]
            if added:
                for f in filter_fields:
                    if f.name not in names:
                        existing.fields.append(f)
                client.create_or_update_index(existing)
                logger.info("Search index updated — added fields: %s", ", ".join(added))
            else:
                logger.info("Search index already has filter fields")
            return True
        except ResourceNotFoundError:
            client.create_or_update_index(_full_index())
            logger.info("Search index created successfully")
            return True
    except Exception as e:
        logger.error(f"Failed to create/update index: {e}")
        return False


def index_has_filter_fields() -> bool:
    """True when progress_pct exists on the live index (indexer may map it)."""
    client = get_index_client()
    if not client:
        return False
    try:
        from azure.core.exceptions import ResourceNotFoundError
        index = client.get_index(settings.AZURE_SEARCH_INDEX)
        return "progress_pct" in {f.name for f in index.fields}
    except ResourceNotFoundError:
        return False
    except Exception:
        return False


def index_documents(documents: List[Dict[str, Any]], embed: bool = True):
    """
    DEPRECATED for application runtime — use Azure SQL Indexer only.
    Kept for one-off setup/debug scripts; do not call from API routes or upload handlers.
    """
    client = get_search_client()
    if not client:
        logger.warning("Azure Search not configured — skipping indexing")
        return

    # Add vectors (gracefully skipped if OpenAI not configured)
    if embed:
        logger.info(f"Generating embeddings for {len(documents)} docs…")
        documents = [_add_vector(doc) for doc in documents]
        embedded = sum(1 for d in documents if VECTOR_FIELD in d)
        logger.info(f"Embeddings generated: {embedded}/{len(documents)}")

    batch_size = 50
    total_ok = 0
    total_fail = 0
    for i in range(0, len(documents), batch_size):
        batch = documents[i:i + batch_size]
        try:
            results = client.upload_documents(documents=batch)
            for r in results:
                if r.succeeded:
                    total_ok += 1
                else:
                    total_fail += 1
                    logger.error(f"Failed to index doc '{r.key}': {r.error_message}")
        except Exception as e:
            logger.error(f"Batch upload error (batch {i // batch_size}): {e}")
    logger.info(f"Indexed {total_ok} docs OK, {total_fail} failed")


def build_project_doc(project) -> Dict[str, Any]:
    pm_name = ""
    try:
        pm_name = project.project_manager.full_name if project.project_manager else ""
    except Exception:
        pass
    budget_str = f"budget ₹{project.budget:.2f}" if project.budget else ""
    date_str = ""
    if project.start_date:
        date_str += f" start {project.start_date}"
    if project.end_date:
        date_str += f" end {project.end_date}"
    return {
        "id": f"project-{project.id}",
        "title": project.name,
        "content": (
            f"{project.name} {project.description or ''} {project.location or ''} "
            f"{pm_name} project manager {budget_str} {date_str} "
            f"progress {project.progress}%"
        ).strip(),
        "content_type": "project",
        "url": f"/projects/{project.id}",
        "metadata": json.dumps({
            "status": project.status.value if project.status else "",
            "location": project.location or "",
            "progress": project.progress,
            "budget": project.budget,
            "start_date": str(project.start_date) if project.start_date else "",
            "end_date": str(project.end_date) if project.end_date else "",
            "project_manager": pm_name,
        }),
    }


def build_task_doc(task) -> Dict[str, Any]:
    project_name = task.project.name if task.project else ""
    assignee_name = ""
    try:
        assignee_name = task.assignee.full_name if task.assignee else ""
    except Exception:
        pass
    due_str = f"due {task.due_date}" if task.due_date else ""
    url = f"/tasks?taskId={task.id}" if not task.project_id else f"/projects/{task.project_id}?tab=Tasks&taskId={task.id}"
    return {
        "id": f"task-{task.id}",
        "title": task.title,
        "content": (
            f"{task.title} {task.description or ''} {project_name} "
            f"assigned to {assignee_name} {due_str}"
        ).strip(),
        "content_type": "task",
        "url": url,
        "metadata": json.dumps({
            "status": task.status.value if task.status else "",
            "priority": task.priority.value if task.priority else "",
            "project_id": task.project_id,
            "project_name": project_name,
            "task_id": task.id,
            "assignee": assignee_name,
            "due_date": str(task.due_date) if task.due_date else "",
        }),
    }


def build_document_doc(doc) -> Dict[str, Any]:
    project_name = doc.project.name if doc.project else ""
    uploader_name = ""
    try:
        uploader_name = doc.uploader.full_name if doc.uploader else ""
    except Exception:
        pass
    upload_date = ""
    upload_display = ""
    if doc.created_at:
        dt = doc.created_at.date() if hasattr(doc.created_at, "date") else doc.created_at
        upload_date = str(dt)
        upload_display = dt.strftime("%B %d %Y").replace(" 0", " ")
    size_bytes = int(doc.file_size or 0)
    size_kb = round(size_bytes / 1024, 1) if size_bytes else 0
    size_mb = round(size_bytes / (1024 * 1024), 2) if size_bytes else 0
    size_label = f"{size_mb} MB" if size_mb >= 1 else (f"{size_kb} KB" if size_kb else "unknown size")
    return {
        "id": f"document-{doc.id}",
        "title": doc.name,
        "content": (
            f"{doc.name} {doc.file_type or ''} {project_name} "
            f"uploaded by {uploader_name} uploaded on {upload_date} {upload_display} "
            f"file size {size_bytes} bytes {size_label} {size_kb} KB {size_mb} MB"
        ).strip(),
        "content_type": "document",
        "url": f"/documents?docId={doc.id}",
        "metadata": json.dumps({
            "file_type": doc.file_type or "",
            "project_id": doc.project_id,
            "project_name": project_name,
            "doc_id": doc.id,
            "uploader": uploader_name,
            "file_url": doc.file_url or "",
            "file_size": size_bytes,
            "file_size_kb": size_kb,
            "file_size_mb": size_mb,
            "file_size_display": size_label,
            "upload_date": upload_date,
            "upload_date_display": upload_display,
        }),
    }


def build_team_doc(member) -> Dict[str, Any]:
    """One search doc per project assignment (legacy)."""
    user = member.user
    if not user:
        return None
    return _build_workforce_user_doc(user)


def _build_workforce_user_doc(user, project_names: List[str] = []) -> Dict[str, Any]:
    """One doc per person — matches Workforce page (8 unique users)."""
    role = user.role.value if user.role else ""
    projects_str = " ".join(project_names)
    return {
        "id": f"workforce-{user.id}",
        "title": user.full_name,
        "content": (
            f"{user.full_name} {role} {user.company_name or ''} "
            f"{projects_str} "
            f"workforce personnel labour LMS team member staff registered total"
        ).strip(),
        "content_type": "team",
        "url": f"/team?userId={user.id}",
        "metadata": json.dumps({
            "role": role,
            "email": user.email,
            "user_id": user.id,
            "projects": project_names,
        }),
    }


def build_unique_workforce_docs(members) -> List[Dict[str, Any]]:
    """Deduplicate by user_id, collecting all assigned project names per person."""
    # Collect all project names per user first
    user_projects: Dict[int, List[str]] = {}
    user_obj: Dict[int, Any] = {}
    for member in members:
        user = member.user
        if not user:
            continue
        if user.id not in user_obj:
            user_obj[user.id] = user
            user_projects[user.id] = []
        if member.project and member.project.name:
            name = member.project.name
            if name not in user_projects[user.id]:
                user_projects[user.id].append(name)

    docs: List[Dict[str, Any]] = []
    for uid, user in user_obj.items():
        docs.append(_build_workforce_user_doc(user, user_projects.get(uid, [])))
    return docs
