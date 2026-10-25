"""Read a bundle lazily: the index first, a class only when it is needed."""

import json
import zipfile
from collections.abc import Callable
from pathlib import Path

from .model import Bundle
from .model import Catalogue
from .model import DocsDocument
from .model import Index
from .model import MemberRef
from .model import ResolvedAttribute
from .model import ResolvedChild
from .model import ResolvedClass
from .model import ResolvedDocument
from .model import Specialisation

Group = ResolvedClass | Specialisation

INDEX_FILE = "index.json"
RESOLVED_DIR = "resolved"
DOCS_DIR = "docs"


class BundleReader:
    """Classes and specialisations with every member listed in full.

    Members given by reference (``{"ref": "NXobject/DATA"}``) are replaced by
    the entry they name; no inheritance is merged here.
    """

    def __init__(
        self,
        index: Index,
        load: Callable[[str], ResolvedDocument | None],
        load_docs: Callable[[str], DocsDocument | None] | None = None,
        close: Callable[[], None] | None = None,
    ) -> None:
        self.index = index
        self._load = load
        self._load_docs = load_docs
        self._close = close
        self._documents: dict[str, ResolvedDocument | None] = {}
        self._groups: dict[str, Group | None] = {}
        self._docs: dict[str, dict[str, str]] = {}

    def close(self) -> None:
        """Release the file the bundle is read from (a zip file)."""
        if self._close is not None:
            self._close()
            self._close = None

    def __enter__(self) -> "BundleReader":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @classmethod
    def open(cls, path: Path | str) -> "BundleReader":
        """A generated directory (``index.json`` + ``resolved/``), the same as a
        ``*.zip`` file (both read lazily), or a bundle file (``*.json``, read at once).
        """
        path = Path(path)
        if path.is_dir():
            return cls.from_directory(path)
        if path.suffix == ".zip":
            return cls.from_zip(path)
        return cls.from_bundle(Bundle.model_validate_json(path.read_text()))

    @classmethod
    def from_zip(cls, path: Path) -> "BundleReader":
        archive = zipfile.ZipFile(path)
        try:
            names = set(archive.namelist())
            index = Index.model_validate_json(archive.read(INDEX_FILE))
        except Exception:
            archive.close()
            raise

        def read(member: str) -> bytes | None:
            return archive.read(member) if member in names else None

        def load(name: str) -> ResolvedDocument | None:
            data = read(f"{RESOLVED_DIR}/{name}.json")
            return ResolvedDocument.model_validate_json(data) if data else None

        def load_docs(name: str) -> DocsDocument | None:
            data = read(f"{DOCS_DIR}/{name}.json")
            return DocsDocument.model_validate_json(data) if data else None

        return cls(index, load, load_docs, archive.close)

    @classmethod
    def from_directory(cls, root: Path) -> "BundleReader":
        index = Index.model_validate_json((root / INDEX_FILE).read_text())

        def load(name: str) -> ResolvedDocument | None:
            path = root / RESOLVED_DIR / f"{name}.json"
            if not path.exists():
                return None
            return ResolvedDocument.model_validate_json(path.read_text())

        def load_docs(name: str) -> DocsDocument | None:
            path = root / DOCS_DIR / f"{name}.json"
            if not path.exists():
                return None
            return DocsDocument.model_validate_json(path.read_text())

        return cls(index, load, load_docs)

    @classmethod
    def from_bundle(
        cls, bundle: Bundle, docs: dict[str, dict[str, str]] | None = None
    ) -> "BundleReader":
        index = Index(**{k: v for k, v in dict(bundle).items() if k != "documents"})

        def load_docs(name: str) -> DocsDocument | None:
            if docs is None or name not in docs:
                return None
            return DocsDocument(texts=docs[name])

        return cls(index, bundle.documents.get, load_docs)

    # ------------------------------------------------------------------ access

    def document(self, name: str) -> ResolvedDocument | None:
        """The resolved document of a class as stored (members may be references)."""
        if name not in self._documents:
            self._documents[name] = (
                self._load(name) if name in self.index.classes else None
            )
        return self._documents[name]

    def _raw_group(self, group_id: str) -> Group | None:
        document = self.document(group_id.split("/", 1)[0])
        if document is None:
            return None
        if "/" in group_id:
            return document.specialisations.get(group_id)
        return document.definition

    def group(self, group_id: str) -> Group | None:
        """A class or specialisation with every member in full."""
        if group_id not in self._groups:
            raw = self._raw_group(group_id)
            if raw is not None:
                raw = raw.model_copy(
                    update={
                        "children": [self._deref(m) for m in raw.children],
                        "attributes": [self._deref(m) for m in raw.attributes],
                    }
                )
            self._groups[group_id] = raw
        return self._groups[group_id]

    def _deref(self, member):
        if not isinstance(member, MemberRef):
            return member
        if member.node is None:
            home, label = member.ref.rsplit("@", 1)
            path, attribute = self._scope(home, 0), label
        else:
            path, attribute = self._scope(member.ref, 1), None
        group, steps = path
        found = None
        for index, step in enumerate(steps):
            last = index == len(steps) - 1 and attribute is None
            candidates = [
                c
                for c in (group.children if group is not None else [])
                if isinstance(c, ResolvedChild)
                and c.id == step
                and (c.node == member.node if last else c.node == "group")
            ]
            if not candidates:
                group = None
                break
            found = candidates[0]
            if not last:
                group = self._raw_group(found.specialisation or found.class_ or "")
        if attribute is not None:
            for candidate in group.attributes if group is not None else []:
                if isinstance(candidate, ResolvedAttribute) and candidate.id == label:
                    return candidate
        elif found is not None and group is not None:
            return found
        raise KeyError(f"reference {member.ref!r} names no member")

    def _scope(self, ref: str, steps: int) -> tuple[Group | None, list[str]]:
        """The longest prefix that is a class or specialisation id and leaves at
        least ``steps`` labels, and the label path after it (§6.3)."""
        parts = ref.split("/")
        for end in range(len(parts) - steps, 0, -1):
            group = self._raw_group("/".join(parts[:end]))
            if group is not None:
                return group, parts[end:]
        return None, parts

    def doc(self, key: str) -> str | None:
        """A documentation text by key; its class is the first part of the key."""
        name = key.split("/", 1)[0].split("@", 1)[0].split("#", 1)[0].split("=", 1)[0]
        if name not in self._docs:
            loaded = self._load_docs(name) if self._load_docs else None
            self._docs[name] = loaded.texts if loaded else {}
        return self._docs[name].get(key)

    def loaded(self) -> list[str]:
        """The classes read so far."""
        return sorted(n for n, d in self._documents.items() if d is not None)


def write_zip(
    path: Path,
    index: Index,
    documents: dict[str, ResolvedDocument],
    docs: dict[str, dict[str, str]] | None = None,
) -> None:
    """A bundle as one zip file that a reader opens lazily."""

    def dump(model) -> str:
        data = model.model_dump(by_alias=True, exclude_none=True, mode="json")
        return json.dumps(
            data, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(INDEX_FILE, dump(index))
        for name, document in sorted(documents.items()):
            archive.writestr(f"{RESOLVED_DIR}/{name}.json", dump(document))
        for name, texts in sorted((docs or {}).items()):
            archive.writestr(
                f"{DOCS_DIR}/{name}.json",
                dump(DocsDocument(texts=dict(sorted(texts.items())))),
            )


def write_docs_document(texts: dict[str, str], path: Path) -> None:
    """One class's documentation texts as canonical JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = DocsDocument(texts=dict(sorted(texts.items()))).model_dump(mode="json")
    path.write_text(
        json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    )


CATALOGUE_FILE = "nxds-index.json"


def select_bundle(directory: Path, release: str | None) -> tuple[Path, bool]:
    """The bundle of a catalogue directory for a release (§12.3), and whether it
    is of that release: the latest revision that is not withdrawn, else (and
    without a release) the newest current bundle."""
    catalogue = Catalogue.model_validate_json((directory / CATALOGUE_FILE).read_text())
    usable = [b for b in catalogue.bundles if b.status != "withdrawn"]
    if release is not None:
        wanted = _release_key(release)
        matching = [b for b in usable if _release_key(b.release) == wanted]
        if matching:
            best = max(matching, key=lambda b: b.revision)
            return directory / best.path, True
    current = [b for b in usable if b.status == "current"] or usable
    if not current:
        raise ValueError(f"{directory / CATALOGUE_FILE}: no usable bundle")
    best = max(current, key=lambda b: (b.release, b.revision))
    return directory / best.path, False


def _release_key(release: str) -> str:
    return release.removeprefix("v").split(".post")[0]
