"""Datapacks del mundo del servidor."""

import zipfile

from modnex.services import release
from modnex.services.servers import server_path


def world_dir(name):
    p = server_path(name)
    level = "world"
    props = p / "server.properties"
    if props.exists():
        for line in props.read_text(errors="replace").splitlines():
            if line.startswith("level-name="):
                level = line.split("=", 1)[1].strip() or "world"
    w = (p / level).resolve()
    if w.parent != p.resolve():
        raise ValueError("level-name no válido en server.properties")
    return w


def datapacks_dir(name, create=False):
    d = world_dir(name) / "datapacks"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def list_datapacks(name):
    d = datapacks_dir(name)
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.iterdir(), key=lambda x: x.name.lower()):
        if f.is_file() and f.suffix == ".zip":
            out.append({"file": f.name, "kind": "zip", "size": f.stat().st_size})
        elif f.is_dir():
            out.append({"file": f.name, "kind": "carpeta", "size": None})
    return out


def finish_datapack(name, tmp, fname):
    if not zipfile.is_zipfile(tmp):
        tmp.unlink(missing_ok=True)
        raise ValueError("el archivo no es un zip válido")
    with zipfile.ZipFile(tmp) as z:
        if "pack.mcmeta" not in z.namelist():
            tmp.unlink(missing_ok=True)
            raise ValueError("no parece un datapack: falta pack.mcmeta en la raíz del zip")
    tmp.replace(datapacks_dir(name, create=True) / fname)


def delete_datapack(name, fname):
    fname = release.safe_zip_name(fname)
    p = datapacks_dir(name) / fname
    if not p.is_file():
        raise FileNotFoundError("datapack no encontrado")
    p.unlink()
