"""Baixa dos Dados Abertos do TSE (cdn.tse.jus.br) os candidatos das Eleições 2026
de SP e de presidente, com fotos reduzidas, e grava em data/candidatos.json e fotos/.

O DivulgaCandContas bloqueia acessos de fora do Brasil (inclusive o GitHub Actions),
mas o CDN de dados abertos é público. Roda em .github/workflows/atualizar-candidatos.yml.
"""
import csv
import io
import json
import os
import re
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone

from PIL import Image

ANO = 2026
CDN = "https://cdn.tse.jus.br/estatistica/sead"
URL_CAND = f"{CDN}/odsele/consulta_cand/consulta_cand_{ANO}.zip"
URL_FOTOS = f"{CDN}/eleicoes/eleicoes{ANO}/fotos/foto_cand{ANO}_{{uf}}_div.zip"
# cargo -> arquivo (UF) em que aparece
CARGOS = {1: "BR", 3: "SP", 5: "SP", 6: "SP", 7: "SP"}
VICES = {2: 1, 4: 3}  # vice-presidente -> presidente, vice-governador -> governador
FOTO_W, FOTO_H = 150, 200


def baixar(url):
    print("Baixando", url, flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 cola-eleitoral"})
    with urllib.request.urlopen(req, timeout=600) as r:
        dados = r.read()
    print(f"  {len(dados) / 1e6:.1f} MB", flush=True)
    return dados


def vazio(v):
    return v is None or v.strip() == "" or v.strip().startswith("#") or v.strip() in ("-1", "-3")


def titulo(s):
    s = (s or "").strip()
    return "" if vazio(s) else s[:1].upper() + s[1:].lower()


def ler_csv(z, nome):
    raw = z.read(nome)
    for enc in ("latin-1", "utf-8-sig"):
        try:
            txt = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    return list(csv.DictReader(io.StringIO(txt), delimiter=";"))


def main():
    zc = zipfile.ZipFile(io.BytesIO(baixar(URL_CAND)))
    nomes = zc.namelist()
    print("Arquivos no zip:", [n for n in nomes if n.lower().endswith(".csv")][:40])

    linhas = []
    for uf in ("BR", "SP"):
        arq = next((n for n in nomes if re.search(rf"_{uf}\.csv$", n, re.I)), None)
        if not arq:
            sys.exit(f"CSV de {uf} não encontrado no zip")
        rows = ler_csv(zc, arq)
        print(f"{arq}: {len(rows)} linhas; colunas: {list(rows[0].keys()) if rows else []}")
        linhas += rows

    turno1 = [r for r in linhas if (r.get("NR_TURNO") or "1").strip() == "1"]
    cargos = {c: [] for c in CARGOS}
    vices = {}
    cod_eleicao = {}
    for r in turno1:
        try:
            cd = int(r["CD_CARGO"])
        except (KeyError, ValueError):
            continue
        uf = r.get("SG_UF", "").strip()
        if cd in VICES:
            vices[(VICES[cd], r["NR_CANDIDATO"].strip())] = r.get("NM_URNA_CANDIDATO", "").strip()
            continue
        if cd not in CARGOS or (CARGOS[cd] != "BR" and uf != CARGOS[cd]):
            continue
        cod_eleicao.setdefault(r.get("CD_ELEICAO", "").strip(), r.get("DS_ELEICAO", "").strip())
        sit = next((r.get(k) for k in ("DS_DETALHE_SITUACAO_CAND", "DS_SITUACAO_CANDIDATURA")
                    if not vazio(r.get(k))), "")
        pnum = r.get("NR_PARTIDO", "").strip()
        cargos[cd].append({
            "id": int(r["SQ_CANDIDATO"]),
            "n": r["NR_CANDIDATO"].strip(),
            "nome": r.get("NM_URNA_CANDIDATO", "").strip(),
            "completo": r.get("NM_CANDIDATO", "").strip(),
            "sigla": r.get("SG_PARTIDO", "").strip(),
            "pnum": pnum.zfill(2) if pnum.isdigit() else "",
            "sit": titulo(sit),
            "vice": "",
        })
    for cd, lista in cargos.items():
        vistos = {}
        for c in lista:
            vistos.setdefault(c["n"], []).append(c["id"])
        for n, ids_n in vistos.items():
            if len(ids_n) > 1:
                print(f"Número repetido cargo {cd} nº {n}:")
                for r in turno1:
                    if r.get("NR_CANDIDATO", "").strip() == n and r.get("CD_CARGO") == str(cd) and (cd == 1 or r.get("SG_UF") == "SP"):
                        print("   ", {k: v for k, v in r.items() if k.startswith(("SQ_", "NM_URNA", "DS_SITUACAO", "DS_DETALHE", "CD_SITUACAO", "DT_GERACAO", "HH_", "CD_ELEICAO", "DS_ELEICAO", "ST_"))})
    for cd, lista in cargos.items():
        for c in lista:
            c["vice"] = vices.get((cd, c["n"]), "")
        lista.sort(key=lambda c: c["n"])
        print(f"Cargo {cd}: {len(lista)} candidatos")
    if not cargos[1] or not cargos[3]:
        sys.exit("Lista de presidente/governador vazia — não gravando.")

    # Fotos: só dos candidatos que o app usa, reduzidas para ~5 KB cada
    ids = {c["id"] for l in cargos.values() for c in l}
    os.makedirs("fotos", exist_ok=True)
    com_foto = set()
    for uf in ("BR", "SP"):
        try:
            zf = zipfile.ZipFile(io.BytesIO(baixar(URL_FOTOS.format(uf=uf))))
        except Exception as e:  # sem fotos ainda: o app mostra as iniciais
            print(f"Fotos de {uf} indisponíveis: {e}")
            continue
        for nome in zf.namelist():
            m = re.search(r"(\d{9,})", os.path.basename(nome))
            if not m or int(m.group(1)) not in ids:
                continue
            sq = int(m.group(1))
            destino = f"fotos/{sq}.jpg"
            if not os.path.exists(destino):
                try:
                    im = Image.open(io.BytesIO(zf.read(nome))).convert("RGB")
                    # recorte 3:4 centralizado e redução
                    w, h = im.size
                    alvo = FOTO_W / FOTO_H
                    if w / h > alvo:
                        nw = int(h * alvo); im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
                    else:
                        nh = int(w / alvo); im = im.crop((0, 0, w, nh))
                    im = im.resize((FOTO_W, FOTO_H), Image.LANCZOS)
                    im.save(destino, "JPEG", quality=72, optimize=True, progressive=True)
                except Exception as e:
                    print("  foto com erro:", nome, e)
                    continue
            com_foto.add(sq)
    for l in cargos.values():
        for c in l:
            c["foto"] = c["id"] in com_foto
    print(f"Fotos: {len(com_foto)} de {len(ids)} candidatos")

    cod = max(cod_eleicao, key=lambda k: k or "") if cod_eleicao else ""
    saida = {
        "eleicao": {"id": cod, "nome": cod_eleicao.get(cod) or f"Eleições Gerais {ANO}", "ano": ANO},
        "fonte": "Dados Abertos do TSE (consulta_cand)",
        "atualizado": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "cargos": {str(k): v for k, v in cargos.items()},
    }
    os.makedirs("data", exist_ok=True)
    # só regrava se os candidatos mudaram (evita commit a cada execução)
    antigo = None
    if os.path.exists("data/candidatos.json"):
        with open("data/candidatos.json", encoding="utf-8") as f:
            antigo = json.load(f)
    if antigo and antigo.get("cargos") == saida["cargos"]:
        print("Candidatos sem mudança.")
        return
    with open("data/candidatos.json", "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, separators=(",", ":"))
    print("Gravado data/candidatos.json")


if __name__ == "__main__":
    main()
