#!/usr/bin/env python3
"""
Revisor de cadastro de evento — Ingresso Digital
================================================

Compara o CADASTRO (texto que a produção envia) com o que está NO AR na
página pública de vendas (ingressodigital.com), apontando divergências.

Fluxo:
  1. parse_cadastro(texto)  -> dict estruturado a partir do texto livre
  2. scrape_evento(link)    -> dict estruturado raspado do site (público + /comprar)
  3. comparar(cadastro, site) -> lista de checagens com status ok/divergente/extra/faltando/info

Sem dependências além de `requests` (que já está instalado).
Uso CLI:
    python3 revisor.py <link>            # só raspa e imprime o que está no ar
    python3 revisor.py --teste           # roda o exemplo embutido (cadastro + link)
"""
from __future__ import annotations

import re
import sys
import html as H
import unicodedata
from dataclasses import dataclass, field, asdict

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

MESES = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril", 5: "maio", 6: "junho",
    7: "julho", 8: "agosto", 9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
}

UF_NOME = {
    "AC": "acre", "AL": "alagoas", "AP": "amapá", "AM": "amazonas", "BA": "bahia",
    "CE": "ceará", "DF": "distrito federal", "ES": "espírito santo", "GO": "goiás",
    "MA": "maranhão", "MT": "mato grosso", "MS": "mato grosso do sul", "MG": "minas gerais",
    "PA": "pará", "PB": "paraíba", "PR": "paraná", "PE": "pernambuco", "PI": "piauí",
    "RJ": "rio de janeiro", "RN": "rio grande do norte", "RS": "rio grande do sul",
    "RO": "rondônia", "RR": "roraima", "SC": "santa catarina", "SP": "são paulo",
    "SE": "sergipe", "TO": "tocantins",
}
NOME_UF = {v: k for k, v in UF_NOME.items()}


# --------------------------------------------------------------------------- #
# Utilidades de normalização
# --------------------------------------------------------------------------- #
def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def norm(s: str | None) -> str:
    """minúsculas, sem acento, espaços colapsados — para comparação tolerante."""
    if not s:
        return ""
    s = H.unescape(s)
    s = strip_accents(s).lower()
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def money_to_float(s: str) -> float | None:
    m = re.search(r"([\d.]+,\d{2}|\d+)", s)
    if not m:
        return None
    v = m.group(1).replace(".", "").replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return None


def fmt_money(v: float | None) -> str:
    if v is None:
        return "—"
    return ("R$ %0.2f" % v).replace(".", ",")


# --------------------------------------------------------------------------- #
# Modelo
# --------------------------------------------------------------------------- #
@dataclass
class Setor:
    nome: str = ""
    inteira: float | None = None
    meia: float | None = None
    outros: dict = field(default_factory=dict)   # ex.: {"Clube GT": 70.0}
    taxa_pct: float | None = None                # % de conveniência detectada


# --------------------------------------------------------------------------- #
# 1) Parser do CADASTRO (texto livre da produção)
# --------------------------------------------------------------------------- #
# rótulo interno -> lista de sinônimos que aparecem no texto
LABELS = [
    ("nome",       [r"show", r"evento", r"atra[cç][aã]o", r"espet[aá]culo"]),
    ("cidade",     [r"cidade"]),
    ("data",       [r"data"]),
    ("local",      [r"local", r"teatro", r"casa"]),
    ("endereco",   [r"endere[cç]o"]),
    ("capacidade", [r"capacidade", r"lota[cç][aã]o"]),
    ("plateia",    [r"plateia numerada", r"plat[eé]ia numerada", r"numera[cç][aã]o"]),
    ("etiquetas",  [r"precisa de etiquetas", r"etiquetas"]),
    ("horario",    [r"hor[aá]rio", r"hora"]),
    ("setores",    [r"valores\s*/?\s*setores", r"valores", r"setores", r"ingressos"]),
    ("taxa",       [r"taxa de conveni[eê]ncia", r"taxa"]),
    ("bloqueios",  [r"bloqueios\s*/?\s*cortesias", r"bloqueios", r"cortesias"]),
]


def parse_cadastro(texto: str) -> dict:
    """Extrai campos do texto livre. Resiliente ao formato 'run-on' com muitos espaços."""
    t = texto.replace("\r", "\n")
    # Acha posições de todos os rótulos conhecidos.
    hits = []  # (pos, fim_label, chave)
    for chave, syns in LABELS:
        for syn in syns:
            for m in re.finditer(rf"(?im)(?:^|[\n\t ;])({syn})\s*[:\-]?\s*", t):
                hits.append((m.start(1), m.end(), chave))
    # Ordena por posição e, no mesmo ponto, prioriza o rótulo de match mais
    # longo (ex.: "Valores / Setores" vence "Valores"; "Bloqueios/Cortesias"
    # vence "Bloqueios").
    hits.sort(key=lambda x: (x[0], -x[1]))
    filtrados = []
    usados = set()
    ocupado_ate = -1
    for pos, fim, chave in hits:
        if pos < ocupado_ate:
            continue
        if chave in usados:
            continue
        filtrados.append((pos, fim, chave))
        usados.add(chave)
        ocupado_ate = fim
    filtrados.sort()

    campos: dict[str, str] = {}
    for i, (pos, fim, chave) in enumerate(filtrados):
        prox = filtrados[i + 1][0] if i + 1 < len(filtrados) else len(t)
        valor = t[fim:prox].strip(" \t\n:-")
        valor = re.sub(r"\s+", " ", valor).strip()
        if valor:
            campos[chave] = valor

    out: dict = {"_campos": campos}
    out["nome"]       = campos.get("nome")
    out["cidade"]     = _parse_cidade(campos.get("cidade"))
    out["data"]       = _parse_data_cadastro(campos.get("data"))
    out["local"]      = campos.get("local")
    out["endereco"]   = campos.get("endereco")
    out["capacidade"] = _primeiro_int(campos.get("capacidade"))
    out["plateia"]    = campos.get("plateia")
    out["etiquetas"]  = campos.get("etiquetas")
    out["horario"]    = _parse_hora(campos.get("horario"))
    out["taxa_pct"]   = _parse_pct(campos.get("taxa") or texto)
    out["setores"]    = _parse_setores_cadastro(campos.get("setores"))
    out["bloqueios"]  = campos.get("bloqueios")
    return out


def _primeiro_int(s: str | None) -> int | None:
    if not s:
        return None
    m = re.search(r"\d+", s.replace(".", ""))
    return int(m.group()) if m else None


def _parse_pct(s: str | None) -> float | None:
    if not s:
        return None
    m = re.search(r"(\d{1,2})\s*%", s)
    return float(m.group(1)) if m else None


def _parse_hora(s: str | None) -> str | None:
    if not s:
        return None
    m = re.search(r"(\d{1,2})\s*[:h]\s*(\d{2})?", s)
    if not m:
        return None
    h = int(m.group(1))
    mm = m.group(2) or "00"
    return f"{h:02d}:{mm}"


def _parse_cidade(s: str | None) -> dict | None:
    if not s:
        return None
    # "Araçatuba, SP"  /  "Araçatuba - SP"  /  "Araçatuba/SP"
    m = re.match(r"\s*(.+?)\s*[,\-/]\s*([A-Za-zÀ-ÿ]{2,})\s*$", s)
    if m:
        cid, uf = m.group(1), m.group(2)
        return {"cidade": cid.strip(), "uf": _uf(uf)}
    return {"cidade": s.strip(), "uf": None}


def _uf(token: str) -> str | None:
    t = token.strip()
    if len(t) == 2 and t.upper() in UF_NOME:
        return t.upper()
    n = norm(t)
    return NOME_UF.get(n)


def _parse_data_cadastro(s: str | None) -> dict | None:
    if not s:
        return None
    m = re.search(r"(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2,4}))?", s)
    if not m:
        return None
    dia, mes = int(m.group(1)), int(m.group(2))
    ano = m.group(3)
    ano = int(ano) + (2000 if ano and len(ano) == 2 else 0) if ano else None
    return {"dia": dia, "mes": mes, "ano": ano, "raw": s}


def _parse_setores_cadastro(s: str | None) -> list[Setor]:
    """'3 setores: 140/79 , 120/60 e ingresso social 35' -> [Setor, ...]"""
    if not s:
        return []
    # Remove o prefixo 'N setores:' se houver.
    s = re.sub(r"(?i)^\s*\d+\s*setores?\s*:?", "", s).strip()
    # Quebra por vírgula e por ' e '.
    tokens = re.split(r"\s*,\s*|\s+e\s+", s)
    setores: list[Setor] = []
    for tok in tokens:
        tok = tok.strip()
        if not tok:
            continue
        nums = re.findall(r"\d+(?:[.,]\d{2})?", tok.replace(".", ""))
        nums = [money_to_float(n) for n in nums]
        nums = [n for n in nums if n is not None]
        if not nums:
            continue
        social = bool(re.search(r"(?i)social|popular", tok))
        nome = re.sub(r"[\d/.,]+", "", tok).strip(" -–—:")
        if "/" in tok and len(nums) >= 2:
            setores.append(Setor(nome=nome or "", inteira=nums[0], meia=nums[1]))
        else:
            setores.append(Setor(nome=(nome or ("Social" if social else "")), inteira=nums[0]))
    return setores


# --------------------------------------------------------------------------- #
# 2) Scraper do site (página pública + /comprar)
# --------------------------------------------------------------------------- #
def _fetch(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=25)
    r.raise_for_status()
    return r.text


def _ids_do_link(link: str) -> tuple[str, str] | None:
    m = re.search(r"/(?:evento|comprar)/(\d+)/([^/?#]+)", link)
    if not m:
        return None
    return m.group(1), m.group(2)


def scrape_evento(link: str) -> dict:
    ids = _ids_do_link(link)
    if not ids:
        raise ValueError("Link não reconhecido. Esperado .../evento/<id>/<slug>")
    eid, slug = ids
    base = "https://ingressodigital.com"
    pub = _fetch(f"{base}/evento/{eid}/{slug}")
    try:
        comp = _fetch(f"{base}/comprar/{eid}/{slug}")
    except Exception:
        comp = ""

    out: dict = {"link": link, "id": eid}

    # nome
    m = re.search(r'property="og:title"\s+content="([^"]+)"', pub)
    out["nome"] = H.unescape(m.group(1)).strip() if m else None

    # local + endereço (bloco do marcador)
    m = re.search(r"marcador\.png.*?<p>([^<]+)</p>\s*<p>([^<]+)</p>", pub, re.S)
    if m:
        out["local"] = H.unescape(m.group(1)).strip()
        out["endereco"] = H.unescape(m.group(2)).strip()
    else:
        out["local"] = out["endereco"] = None

    # cidade/uf a partir do fim do endereço: "..., Araçatuba - São Paulo"
    out["cidade"] = None
    if out.get("endereco"):
        m = re.search(r",\s*([^,\-]+?)\s*-\s*([^,\-]+?)\s*$", out["endereco"])
        if m:
            out["cidade"] = {"cidade": m.group(1).strip(), "uf": _uf(m.group(2))}

    # faixa de preço
    m = re.search(r"['\"]valores-ing['\"]>\s*R\$\s*([\d.,]+)\s*a\s*R\$\s*([\d.,]+)", pub)
    out["faixa_preco"] = (money_to_float(m.group(1)), money_to_float(m.group(2))) if m else None

    # datas: id="collapseMM-DD-YYYY"
    datas = []
    for mm, dd, yy in re.findall(r'id="collapse(\d{2})-(\d{2})-(\d{4})"', pub):
        datas.append({"dia": int(dd), "mes": int(mm), "ano": int(yy)})
    # dedup mantendo ordem
    seen = set(); out["datas"] = []
    for d in datas:
        k = (d["dia"], d["mes"], d["ano"])
        if k not in seen:
            seen.add(k); out["datas"].append(d)

    # horários (botões dd:mm após "Selecione o horário")
    horarios = []
    seg = pub[pub.find("Selecione o hor"):] if "Selecione o hor" in pub else pub
    for hm in re.findall(r">\s*(\d{1,2}:\d{2})\s*<", seg):
        if hm not in horarios:
            horarios.append(hm)
    out["horarios"] = horarios

    # classificação indicativa / indicação de idade
    m = re.search(r'class="classif-evento"[^>]*>(?:\s*<i[^>]*>\s*</i>)?\s*([^<]+?)\s*</p>', pub, re.S)
    out["classificacao"] = None
    if m:
        c = H.unescape(m.group(1)).strip()
        c = re.sub(r"(?i)^classifica[çc][aã]o\s+indicativa\s*:?\s*", "", c).strip()
        out["classificacao"] = c or None

    # release / sinopse ("Sobre o Evento")
    out["release"] = None
    m = re.search(r'id="collapseOne"[^>]*>(.*?)</div>', pub, re.S)
    if not m:
        m = re.search(r'texto-descricao-event"[^>]*>(.*?)</div>', pub, re.S)
    if m:
        txt = re.sub(r"<[^>]+>", " ", m.group(1))
        txt = re.sub(r"\s+", " ", H.unescape(txt)).strip()
        out["release"] = txt or None

    # setores (da página /comprar)
    out["setores"] = _scrape_setores(comp) if comp else []
    return out


def _scrape_setores(comp: str) -> list[Setor]:
    # Posições dos títulos de setor.
    headers = []  # (pos, nome)
    for m in re.finditer(r'class="sector_title"[^>]*>\s*<h6[^>]*>\s*<div>\s*([^<]+?)\s*</div>', comp, re.S):
        headers.append((m.start(), H.unescape(m.group(1)).strip()))
    if not headers:
        return []

    # Blocos de ingresso individuais: lote (h4) + valor + taxa.
    blocos = []
    for m in re.finditer(
        r'<h4>\s*([^<]+?)\s*</h4>.*?val-la-taxa">\s*R\$\s*([\d.,]+)(?:\s*\+\s*R\$\s*([\d.,]+)\s*Taxa)?',
        comp, re.S,
    ):
        blocos.append((m.start(), H.unescape(m.group(1)).strip(),
                       money_to_float(m.group(2)),
                       money_to_float(m.group(3)) if m.group(3) else None))

    # Atribui cada bloco ao setor cujo título o precede.
    def setor_de(pos: int) -> str:
        nome = headers[0][1]
        for hpos, hnome in headers:
            if hpos <= pos:
                nome = hnome
            else:
                break
        return nome

    agrup: dict[str, Setor] = {}
    ordem: list[str] = []
    for pos, lote, valor, taxa in blocos:
        snome = setor_de(pos)
        if snome not in agrup:
            agrup[snome] = Setor(nome=snome)
            ordem.append(snome)
        s = agrup[snome]
        lnorm = norm(lote)
        if "meia" in lnorm:
            s.meia = valor
        elif "inteira" in lnorm or "popular" in lnorm or "social" in lnorm:
            s.inteira = valor
        else:
            s.outros[lote] = valor
        if taxa and valor:
            s.taxa_pct = round(taxa / valor * 100)
    # Se setor não tem 'inteira' marcada, usa o maior valor entre lotes/meia.
    for s in agrup.values():
        if s.inteira is None:
            cand = [v for v in [s.meia, *s.outros.values()] if v is not None]
            if cand:
                s.inteira = max(cand)
    return [agrup[n] for n in ordem]


# --------------------------------------------------------------------------- #
# 3) Comparador
# --------------------------------------------------------------------------- #
@dataclass
class Check:
    campo: str
    cadastro: str
    site: str
    status: str   # ok | divergente | extra | faltando | info
    obs: str = ""


def _contains(a: str, b: str) -> bool:
    """True se o menor estiver contido no maior (após normalizar)."""
    a, b = norm(a), norm(b)
    if not a or not b:
        return False
    return a in b or b in a


def comparar(cad: dict, site: dict) -> list[Check]:
    checks: list[Check] = []

    # Nome
    cn, sn = cad.get("nome"), site.get("nome")
    if cn and sn:
        ok = _contains(cn, sn) or _palavras_em_comum(cn, sn) >= 0.6
        checks.append(Check("Nome do evento", cn, sn, "ok" if ok else "divergente"))
    elif sn:
        checks.append(Check("Nome do evento", cn or "—", sn, "info", "sem nome no cadastro"))

    # Cidade / UF
    cc, sc = cad.get("cidade"), site.get("cidade")
    if cc and sc:
        ok = _contains(cc["cidade"], sc["cidade"])
        uf_ok = (not cc.get("uf") or not sc.get("uf") or cc["uf"] == sc["uf"])
        c_str = f'{cc["cidade"]}{("/"+cc["uf"]) if cc.get("uf") else ""}'
        s_str = f'{sc["cidade"]}{("/"+sc["uf"]) if sc.get("uf") else ""}'
        checks.append(Check("Cidade", c_str, s_str, "ok" if (ok and uf_ok) else "divergente"))

    # Data
    cd, sds = cad.get("data"), site.get("datas") or []
    if cd:
        s_str = ", ".join(f'{d["dia"]:02d}/{d["mes"]:02d}/{d["ano"]}' for d in sds) or "—"
        c_str = cd.get("raw", f'{cd["dia"]:02d}/{cd["mes"]:02d}')
        match = any(d["dia"] == cd["dia"] and d["mes"] == cd["mes"]
                    and (cd.get("ano") in (None, d["ano"])) for d in sds)
        st = "ok" if match else ("divergente" if sds else "info")
        checks.append(Check("Data", c_str, s_str, st,
                            "" if sds else "site não expôs data"))

    # Local
    cl, sl = cad.get("local"), site.get("local")
    if cl and sl:
        checks.append(Check("Local", cl, sl, "ok" if _contains(cl, sl) else "divergente"))

    # Endereço (compara rua + número; CEP costuma só existir no cadastro)
    ce, se = cad.get("endereco"), site.get("endereco")
    if ce and se:
        ok = _endereco_bate(ce, se)
        checks.append(Check("Endereço", ce, se, "ok" if ok else "divergente",
                            "CEP não é exibido no site" if "cep" not in norm(se) else ""))

    # Horário
    ch, shs = cad.get("horario"), site.get("horarios") or []
    if ch:
        s_str = ", ".join(shs) or "—"
        match = ch in shs or any(h.startswith(ch[:2]) for h in shs)
        st = "ok" if match else ("divergente" if shs else "info")
        checks.append(Check("Horário", ch, s_str, st, "" if shs else "site não expôs horário"))

    # Capacidade (não exposta no site público)
    if cad.get("capacidade"):
        checks.append(Check("Capacidade", str(cad["capacidade"]), "—", "info",
                            "não verificável na página pública"))

    # Taxa de conveniência
    ct = cad.get("taxa_pct")
    site_taxas = sorted({s.taxa_pct for s in site.get("setores", []) if s.taxa_pct})
    if ct is not None:
        s_str = ", ".join(f"{int(x)}%" for x in site_taxas) or "—"
        if site_taxas:
            st = "ok" if all(abs(x - ct) <= 1 for x in site_taxas) else "divergente"
        else:
            st = "info"
        checks.append(Check("Taxa de conveniência", f"{int(ct)}%", s_str, st,
                            "" if site_taxas else "não detectada no site"))

    # Release confere com o nome do evento?
    rel = site.get("release")
    nome_ref = site.get("nome") or cad.get("nome") or ""
    if rel:
        preview = (rel[:140] + "…") if len(rel) > 140 else rel
        bate = _release_bate(nome_ref, rel)
        checks.append(Check("Release × nome do evento", nome_ref or "—", preview,
                            "ok" if bate else "divergente",
                            "" if bate else "o release não menciona o nome do evento — confira se é o texto certo"))
    else:
        checks.append(Check("Release × nome do evento", nome_ref or "—", "— (vazio)",
                            "divergente", "evento está no ar SEM release/sinopse"))

    # Classificação indicativa / indicação de idade
    cls = site.get("classificacao")
    checks.append(Check("Classificação indicativa", "—", cls or "não informada no site",
                        "info" if cls else "divergente",
                        "confirme a indicação de idade" if cls else "site não exibe classificação indicativa"))

    # Setores / preços
    checks.extend(_comparar_setores(cad.get("setores", []), site.get("setores", [])))

    # Campos só-informativos do cadastro (não dá pra checar no site público)
    for chave, rotulo in [("plateia", "Plateia numerada"),
                          ("etiquetas", "Etiquetas"),
                          ("bloqueios", "Bloqueios/Cortesias")]:
        if cad.get(chave):
            checks.append(Check(rotulo, cad[chave], "—", "info",
                                "não verificável no site (confira manualmente)"))
    return checks


def _release_bate(nome: str, release: str) -> bool:
    """True se algum termo distintivo do nome do evento aparece no release."""
    GENERICOS = {"show", "evento", "concert", "concerts", "live", "tour", "the", "do",
                 "da", "de", "classicos", "rock", "pop", "festival", "turne"}
    rel = norm(release)
    tokens = [w for w in norm(nome).split() if len(w) >= 4 and w not in GENERICOS]
    if not tokens:
        # nome só tem termos genéricos: exige que ao menos um deles apareça
        tokens = [w for w in norm(nome).split() if len(w) >= 4]
    return any(t in rel for t in tokens) if tokens else True


def _palavras_em_comum(a: str, b: str) -> float:
    sa = set(norm(a).split())
    sb = set(norm(b).split())
    if not sa:
        return 0.0
    return len(sa & sb) / len(sa)


def _endereco_bate(cad: str, site: str) -> bool:
    # Compara os tokens significativos da rua/número, ignorando CEP e cidade/uf.
    def toks(s: str) -> set[str]:
        s = norm(s)
        s = re.sub(r"\b\d{5}-?\d{3}\b", " ", s)  # remove CEP
        palavras = [w for w in re.findall(r"[a-z0-9]+", s) if len(w) >= 3]
        return set(palavras)
    a, b = toks(cad), toks(site)
    if not a:
        return False
    return len(a & b) / len(a) >= 0.6


def _comparar_setores(cad: list[Setor], site: list[Setor]) -> list[Check]:
    checks: list[Check] = []
    site_rest = list(site)

    def achar_match(cs: Setor) -> Setor | None:
        # 1) por preço de inteira igual
        for ss in site_rest:
            if cs.inteira is not None and ss.inteira is not None and abs(cs.inteira - ss.inteira) < 0.01:
                return ss
        # 2) por nome contido
        for ss in site_rest:
            if cs.nome and _contains(cs.nome, ss.nome):
                return ss
        return None

    for cs in cad:
        ss = achar_match(cs)
        rotulo = f"Setor {cs.nome}".strip() if cs.nome else f"Setor (inteira {fmt_money(cs.inteira)})"
        if ss is None:
            checks.append(Check(rotulo,
                                _setor_str(cs), "não encontrado",
                                "faltando",
                                "setor do cadastro não localizado no site"))
            continue
        site_rest.remove(ss)
        obs = []
        st = "ok"
        # inteira
        if cs.inteira is not None and ss.inteira is not None and abs(cs.inteira - ss.inteira) >= 0.01:
            st = "divergente"; obs.append(f"inteira {fmt_money(cs.inteira)}≠{fmt_money(ss.inteira)}")
        # meia
        if cs.meia is not None:
            if ss.meia is None:
                obs.append("site sem meia")
                st = "divergente"
            elif abs(cs.meia - ss.meia) >= 0.01:
                st = "divergente"; obs.append(f"meia {fmt_money(cs.meia)}≠{fmt_money(ss.meia)}")
        rot = f"Setor {ss.nome}".strip() if ss.nome else rotulo
        checks.append(Check(rot, _setor_str(cs), _setor_str(ss), st, "; ".join(obs)))

    # setores que sobraram no site (não estavam no cadastro)
    for ss in site_rest:
        rot = f"Setor {ss.nome}".strip() if ss.nome else f"Setor (inteira {fmt_money(ss.inteira)})"
        checks.append(Check(rot, "não consta", _setor_str(ss), "extra",
                            "setor existe no site mas não está no cadastro"))
    return checks


def _setor_str(s: Setor) -> str:
    partes = []
    if s.inteira is not None:
        partes.append(f"inteira {fmt_money(s.inteira)}")
    if s.meia is not None:
        partes.append(f"meia {fmt_money(s.meia)}")
    for k, v in s.outros.items():
        partes.append(f"{k} {fmt_money(v)}")
    return " · ".join(partes) or "—"


# --------------------------------------------------------------------------- #
# Orquestração + serialização (para o servidor)
# --------------------------------------------------------------------------- #
def revisar(texto_cadastro: str, link: str) -> dict:
    cad = parse_cadastro(texto_cadastro)
    site = scrape_evento(link)
    checks = comparar(cad, site)
    resumo = {
        "ok": sum(c.status == "ok" for c in checks),
        "divergente": sum(c.status == "divergente" for c in checks),
        "extra": sum(c.status == "extra" for c in checks),
        "faltando": sum(c.status == "faltando" for c in checks),
        "info": sum(c.status == "info" for c in checks),
    }
    return {
        "cadastro": _serial(cad),
        "site": _serial(site),
        "checks": [asdict(c) for c in checks],
        "resumo": resumo,
    }


def _serial(obj):
    if isinstance(obj, Setor):
        return asdict(obj)
    if isinstance(obj, dict):
        return {k: _serial(v) for k, v in obj.items() if k != "_campos"}
    if isinstance(obj, (list, tuple)):
        return [_serial(x) for x in obj]
    return obj


# --------------------------------------------------------------------------- #
# CLI / teste
# --------------------------------------------------------------------------- #
EXEMPLO_CADASTRO = """Taxa de conveniencia 15%
Show: Clássicos do Rock      Cidade: Araçatuba, SP      Data: 15/08 - Sábado
Local: Teatro São João
Endereço: R. Dr. Luiz Nogueira Martins, 280 - São João, Araçatuba -16025-025
Capacidade: 302
Plateia Numerada: Sim
Precisa de etiquetas: Não
Horário: 21h
Valores / Setores: 3 setores: 140/79 , 120/60 e ingresso social 35
Bloqueios/ Cortesias: Teatro: 04  Produção nacional: 04"""
EXEMPLO_LINK = "https://ingressodigital.com/evento/21061/starlight-concert-classicos-do-rock"

ICONE = {"ok": "✅", "divergente": "⚠️", "extra": "➕", "faltando": "❌", "info": "ℹ️"}


def _print_cli(res: dict) -> None:
    print(f"\nEVENTO NO AR: {res['site'].get('nome')}")
    print("-" * 70)
    for c in res["checks"]:
        print(f"{ICONE.get(c['status'],'?')} {c['campo']:<26} | cad: {c['cadastro']:<28} | site: {c['site']}"
              + (f"   ({c['obs']})" if c['obs'] else ""))
    print("-" * 70)
    r = res["resumo"]
    print(f"Resumo: {r['ok']} ok · {r['divergente']} divergentes · "
          f"{r['extra']} extra · {r['faltando']} faltando · {r['info']} info\n")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--teste":
        _print_cli(revisar(EXEMPLO_CADASTRO, EXEMPLO_LINK))
    elif len(sys.argv) >= 2:
        site = scrape_evento(sys.argv[1])
        import json
        print(json.dumps(_serial(site), ensure_ascii=False, indent=2))
    else:
        print("uso: python3 revisor.py <link>  |  python3 revisor.py --teste")
