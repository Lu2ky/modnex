"""Pack de texturas del servidor: URL remota o archivo local."""

import hashlib
import json
import re
import urllib.request
import zipfile

from modnex.infra import db
from modnex.services import release
from modnex.config import HERE
from modnex.services.properties import read_properties, write_properties


def get_resourcepack(name):
    p = read_properties(name)
    prompt = p.get("resource-pack-prompt", "")
    try:
        j = json.loads(prompt)
        prompt = j.get("text", "") if isinstance(j, dict) else prompt
    except ValueError:
        pass
    return {"url": p.get("resource-pack", ""), "sha1": p.get("resource-pack-sha1", ""),
            "required": p.get("require-resource-pack", "false") == "true", "prompt": prompt}


def set_resourcepack(name, url, sha1, required, prompt):
    url, sha1, prompt = (url or "").strip(), (sha1 or "").strip().lower(), (prompt or "").strip()
    if url and not re.fullmatch(r"https?://[^\s\\]{4,480}", url):
        raise ValueError("la URL del pack no es válida")
    if sha1 and not re.fullmatch(r"[0-9a-f]{40}", sha1):
        raise ValueError("el SHA-1 debe tener 40 caracteres hexadecimales")
    if len(prompt) > 200 or re.search(r"[\x00-\x1f\x7f\\]", prompt):
        raise ValueError("el mensaje no es válido (máximo 200 caracteres, sin saltos de línea)")
    write_properties(name, {
        "resource-pack": url, "resource-pack-sha1": sha1 if url else "",
        "require-resource-pack": "true" if (required and url) else "false",
        "resource-pack-prompt": json.dumps({"text": prompt}, ensure_ascii=False) if (prompt and url) else ""})


def packs_dir(name):
    d = (HERE / "packs" / name).resolve()
    if d.parent != (HERE / "packs").resolve():
        raise ValueError("servidor no válido")
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_local_packs(name):
    d = packs_dir(name)
    out = []
    for row in db.packs_for(name):
        f = d / row["filename"]
        if f.is_file():
            out.append({"file": row["filename"], "size": f.stat().st_size, "sha1": row["sha1"], "token": row["token"]})
    return out


def finish_pack_upload(name, tmp, fname):
    if not zipfile.is_zipfile(tmp) or "pack.mcmeta" not in zipfile.ZipFile(tmp).namelist():
        tmp.unlink(missing_ok=True)
        raise ValueError("no parece un pack de texturas: falta pack.mcmeta en la raíz del zip")
    sha1 = hashlib.sha1(tmp.read_bytes()).hexdigest()
    tmp.replace(packs_dir(name) / fname)
    db.pack_add(name, fname, sha1)
    return sha1


def delete_local_pack(name, fname):
    fname = release.safe_zip_name(fname)
    p = packs_dir(name) / fname
    if not p.is_file():
        raise FileNotFoundError("pack no encontrado")
    row = next((r for r in db.packs_for(name) if r["filename"] == fname), None)
    p.unlink()
    db.pack_delete(name, fname)
    # Si el servidor lo estaba pidiendo a los jugadores, se quita para no apuntar a un archivo borrado.
    if row and row["token"] in get_resourcepack(name)["url"]:
        set_resourcepack(name, "", "", False, "")


def use_local_pack(name, fname, base_url, required, prompt):
    fname = release.safe_zip_name(fname)
    row = next((r for r in db.packs_for(name) if r["filename"] == fname), None)
    if not row:
        raise FileNotFoundError("pack no encontrado")
    base = (base_url or "").strip().rstrip("/")
    if not re.fullmatch(r"https?://[A-Za-z0-9.\-]+(:\d{1,5})?", base):
        raise ValueError("la dirección pública debe ser como http://192.168.10.18:8765")
    set_resourcepack(name, f"{base}/packs/{row['token']}/{urllib.parse.quote(fname)}", row["sha1"], required, prompt)
