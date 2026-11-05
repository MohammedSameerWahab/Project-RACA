import asyncio
from pathlib import Path

import pytest

from src import pipeline as pipeline_module
from src.pipeline import RACAPipeline, RepositoryIndex
from src.workspace import WorkspaceFile


def prepare_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> RACAPipeline:
    repositories_dir = tmp_path / "repositories"
    index_state_dir = tmp_path / "cocoindex_state"
    data_dir = tmp_path / "data"
    repositories_dir.mkdir()
    data_dir.mkdir()
    monkeypatch.setattr(pipeline_module, "REPOSITORIES_DIR", repositories_dir)
    monkeypatch.setattr(pipeline_module, "INDEX_STATE_DIR", index_state_dir)
    monkeypatch.setattr(pipeline_module, "DATA_DIR", data_dir)

    pipeline = RACAPipeline()
    monkeypatch.setattr(pipeline, "_validate_environment", lambda: None)
    monkeypatch.setattr(pipeline, "_write_manifest", lambda: None)

    async def finish_cleanup() -> None:
        return None

    monkeypatch.setattr(pipeline, "_finish_pending_cleanup", finish_cleanup)
    return pipeline


def test_successful_ingest_switches_only_after_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pipeline = prepare_pipeline(monkeypatch, tmp_path)
    old_path = pipeline_module.REPOSITORIES_DIR / "old-repository"
    old_path.mkdir()
    previous = RepositoryIndex(
        repository="old-repository",
        repository_key="old-repository",
        local_path=old_path,
        postgres_table="raca_code_embeddings",
        cocoindex_state=pipeline_module.DATA_DIR / "cocoindex.db",
        graph_state=pipeline_module.DATA_DIR / "cocoindex_graph.db",
        legacy=True,
    )
    pipeline._active_index = previous
    pipeline.workspace.set_repository(old_path)
    validations: list[Path] = []

    def clone_repository(
        url: str,
        repositories_dir: Path,
        destination_name: str | None = None,
    ) -> Path:
        destination = repositories_dir / str(destination_name)
        destination.mkdir()
        return destination

    async def run_flows(repository: RepositoryIndex) -> None:
        assert pipeline.current_repository == "old-repository"
        assert pipeline.workspace.repository_path == old_path.resolve()

    async def validate_index(repository: RepositoryIndex) -> None:
        validations.append(repository.local_path)

    monkeypatch.setattr(pipeline_module, "clone_repository", clone_repository)
    monkeypatch.setattr(pipeline, "_run_index_flows", run_flows)
    monkeypatch.setattr(pipeline, "_validate_index", validate_index)

    result = asyncio.run(
        pipeline.ingest_repository(
            "https://github.com/acme/new-repository"
        )
    )

    assert validations == [result.local_path]
    assert result.repository == "new-repository"
    assert result.repository_key.startswith("new-repository-")
    assert pipeline.current_repository == "new-repository"
    assert pipeline.workspace.repository_path == result.local_path
    assert old_path.is_dir()
    assert pipeline._pending_cleanup == [previous]


def test_failed_ingest_preserves_active_repository(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pipeline = prepare_pipeline(monkeypatch, tmp_path)
    old_path = pipeline_module.REPOSITORIES_DIR / "old-repository"
    old_path.mkdir()
    previous = RepositoryIndex(
        repository="old-repository",
        repository_key="old-repository",
        local_path=old_path,
        postgres_table="raca_code_embeddings",
        cocoindex_state=pipeline_module.DATA_DIR / "cocoindex.db",
        graph_state=pipeline_module.DATA_DIR / "cocoindex_graph.db",
        legacy=True,
    )
    pipeline._active_index = previous
    pipeline.workspace.set_repository(old_path)

    def clone_repository(
        url: str,
        repositories_dir: Path,
        destination_name: str | None = None,
    ) -> Path:
        destination = repositories_dir / str(destination_name)
        destination.mkdir()
        return destination

    async def fail_index(repository: RepositoryIndex) -> None:
        raise RuntimeError("simulated index failure")

    async def discard_staged(
        repository: RepositoryIndex,
        local_path: Path | None,
        clean_indexes: bool = True,
    ) -> str | None:
        return None

    monkeypatch.setattr(pipeline_module, "clone_repository", clone_repository)
    monkeypatch.setattr(pipeline, "_run_index_flows", fail_index)
    monkeypatch.setattr(pipeline, "_discard_staged_repository", discard_staged)

    with pytest.raises(pipeline_module.PipelineError, match="simulated index failure"):
        asyncio.run(
            pipeline.ingest_repository(
                "https://github.com/acme/new-repository"
            )
        )

    assert pipeline._active_index is previous
    assert pipeline.current_repository == "old-repository"
    assert pipeline.workspace.repository_path == old_path.resolve()
    assert pipeline._pending_cleanup == []


def test_manifest_failure_preserves_active_repository(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pipeline = prepare_pipeline(monkeypatch, tmp_path)
    old_path = pipeline_module.REPOSITORIES_DIR / "old-repository"
    old_path.mkdir()
    previous = RepositoryIndex(
        repository="old-repository",
        repository_key="old-repository",
        local_path=old_path,
        postgres_table="raca_code_embeddings",
        cocoindex_state=pipeline_module.DATA_DIR / "cocoindex.db",
        graph_state=pipeline_module.DATA_DIR / "cocoindex_graph.db",
        legacy=True,
    )
    pipeline._active_index = previous
    pipeline.workspace.set_repository(old_path)
    discarded: list[RepositoryIndex] = []

    def clone_repository(
        url: str,
        repositories_dir: Path,
        destination_name: str | None = None,
    ) -> Path:
        destination = repositories_dir / str(destination_name)
        destination.mkdir()
        return destination

    async def succeed(repository: RepositoryIndex) -> None:
        return None

    def fail_manifest() -> None:
        raise OSError("simulated manifest failure")

    async def discard_staged(
        repository: RepositoryIndex,
        local_path: Path | None,
        clean_indexes: bool = True,
    ) -> str | None:
        discarded.append(repository)
        return None

    monkeypatch.setattr(pipeline_module, "clone_repository", clone_repository)
    monkeypatch.setattr(pipeline, "_run_index_flows", succeed)
    monkeypatch.setattr(pipeline, "_validate_index", succeed)
    monkeypatch.setattr(pipeline, "_write_manifest", fail_manifest)
    monkeypatch.setattr(pipeline, "_discard_staged_repository", discard_staged)

    with pytest.raises(pipeline_module.PipelineError, match="manifest failure"):
        asyncio.run(
            pipeline.ingest_repository(
                "https://github.com/acme/new-repository"
            )
        )

    assert pipeline._active_index is previous
    assert pipeline.current_repository == "old-repository"
    assert pipeline.workspace.repository_path == old_path.resolve()
    assert pipeline._pending_cleanup == []
    assert len(discarded) == 1


def test_saves_during_refresh_are_indexed_afterward(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pipeline = prepare_pipeline(monkeypatch, tmp_path)
    repository = RepositoryIndex(
        repository="sample",
        repository_key="sample-123",
        local_path=pipeline_module.REPOSITORIES_DIR / "sample",
        postgres_table="raca_code_embeddings_123",
        cocoindex_state=pipeline_module.DATA_DIR / "state" / "cocoindex.db",
        graph_state=pipeline_module.DATA_DIR / "state" / "cocoindex_graph.db",
    )
    pipeline._active_index = repository
    first_refresh_started = asyncio.Event()
    allow_first_refresh_to_finish = asyncio.Event()
    flow_calls = 0

    def write_file(path: str, content: str) -> WorkspaceFile:
        return WorkspaceFile(
            path=path,
            name=Path(path).name,
            extension=Path(path).suffix,
            size=len(content),
            content=content,
        )

    async def run_flows(index: RepositoryIndex) -> None:
        nonlocal flow_calls
        flow_calls += 1
        if flow_calls == 1:
            first_refresh_started.set()
            await allow_first_refresh_to_finish.wait()

    async def validate_index(index: RepositoryIndex) -> None:
        return None

    monkeypatch.setattr(pipeline.workspace, "write_file", write_file)
    monkeypatch.setattr(pipeline, "_run_index_flows", run_flows)
    monkeypatch.setattr(pipeline, "_validate_index", validate_index)

    async def save_twice() -> None:
        await pipeline.save_file("first.py", "first", repository.repository_key)
        await asyncio.wait_for(first_refresh_started.wait(), timeout=2)
        second_save = asyncio.create_task(
            pipeline.save_file("second.py", "second", repository.repository_key)
        )
        await asyncio.sleep(0)
        allow_first_refresh_to_finish.set()
        await second_save

        async def wait_until_idle() -> None:
            while pipeline._sync_task is not None:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_until_idle(), timeout=3)

    asyncio.run(save_twice())

    assert flow_calls == 2
    assert pipeline.index_status()["status"] == "ready"
