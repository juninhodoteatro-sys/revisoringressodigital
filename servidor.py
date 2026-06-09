#!/usr/bin/env python3
"""
App web local do Revisor de Cadastro.

Sobe um servidor em http://localhost:8780 com um formulário:
cola o texto do cadastro + o link de vendas -> mostra a revisão campo a campo.

Roda só com a biblioteca padrão + requests (via revisor.py).
    python3 servidor.py
"""
from __future__ import annotations

import os
import html
import traceback
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import revisor

PORT = int(os.environ.get("PORT", "8780"))
LOGO = "/logo.svg"  # servido localmente (same-origin) p/ exportar imagem sem quebrar
LOGO_FILE = Path(__file__).resolve().parent / "logo.svg"
LOGO_SVG = LOGO_FILE.read_bytes() if LOGO_FILE.exists() else b""

STATUS_INFO = {
    "ok":         ("✅", "#1f9d55", "OK"),
    "divergente": ("⚠️", "#d97706", "Diverge"),
    "extra":      ("➕", "#2563eb", "Extra no site"),
    "faltando":   ("❌", "#dc2626", "Faltando no site"),
    "info":       ("ℹ️", "#6b7280", "Conferir"),
}

PAGE_CSS = """
:root{
 --teal:#1d4e5e; --teal-d:#163e4b; --azul:#4cbfe0; --azul-d:#2da6cb;
 --bg:#eef3f5; --card:#ffffff; --line:#dce5e9; --ink:#1d3540; --mut:#6b818b;
 --ok:#188a55; --warn:#d97706; --extra:#2da6cb; --falt:#dc2626; --info:#6b818b;
}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,sans-serif;
 background:var(--bg);color:var(--ink);-webkit-font-smoothing:antialiased}
.topbar{background:#fff;border-bottom:1px solid var(--line)}
.topbar .in{max-width:1040px;margin:0 auto;padding:16px 20px;display:flex;align-items:center;gap:16px}
.topbar img{height:38px}
.topbar .tag{font-size:13px;color:var(--mut);border-left:1px solid var(--line);padding-left:16px;
 font-weight:500}
.wrap{max-width:1040px;margin:0 auto;padding:26px 20px 70px}
h1{font-size:24px;margin:0 0 4px;color:var(--teal);letter-spacing:-.2px}
.sub{color:var(--mut);font-size:13.5px;margin:0 0 22px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:22px;
 box-shadow:0 1px 2px rgba(20,60,75,.04)}
label{display:block;font-size:13px;color:var(--teal);margin:16px 0 6px;font-weight:700}
label:first-of-type{margin-top:0}
textarea,input[type=text]{width:100%;background:#fbfdfe;border:1px solid var(--line);color:var(--ink);
 border-radius:11px;padding:13px 14px;font-size:14.5px;font-family:inherit;transition:border .15s}
textarea:focus,input[type=text]:focus{outline:none;border-color:var(--azul);
 box-shadow:0 0 0 3px rgba(76,191,224,.15)}
textarea{min-height:210px;resize:vertical;line-height:1.55}
.btn{display:inline-flex;align-items:center;gap:8px;border:0;cursor:pointer;font-weight:700;
 font-size:15px;padding:13px 26px;border-radius:11px;text-decoration:none;transition:filter .15s}
.btn-primary{background:var(--teal);color:#fff;margin-top:18px}
.btn-primary:hover{filter:brightness(1.12)}
.btn-ghost{background:#fff;color:var(--teal);border:1.5px solid var(--line)}
.btn-ghost:hover{border-color:var(--azul);color:var(--teal-d)}
.head-row{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}
.card{flex:1;min-width:110px;background:var(--card);border:1px solid var(--line);border-radius:13px;
 padding:16px 12px;text-align:center}
.card .n{font-size:28px;font-weight:800;line-height:1}
.card .l{font-size:11.5px;color:var(--mut);margin-top:6px;font-weight:600}
table{width:100%;border-collapse:collapse;margin-top:6px;background:var(--card);
 border:1px solid var(--line);border-radius:14px;overflow:hidden}
th,td{padding:13px 14px;text-align:left;font-size:13.5px;vertical-align:top;
 border-bottom:1px solid var(--line)}
th{background:#f5f9fb;color:var(--teal);font-size:11.5px;text-transform:uppercase;
 letter-spacing:.5px;font-weight:700}
tr:last-child td{border-bottom:0}
.badge{display:inline-block;padding:4px 11px;border-radius:999px;font-size:11.5px;font-weight:700;
 color:#fff;white-space:nowrap}
.obs{color:var(--mut);font-size:12px;margin-top:4px}
.row-div{background:rgba(217,119,6,.06)}
.row-extra{background:rgba(45,166,203,.06)}
.row-falt{background:rgba(220,38,38,.06)}
.alert{border-radius:12px;padding:14px 16px;margin:18px 0;font-size:14px;font-weight:500;
 background:#fff6ea;border:1px solid #f0d3a3;color:#92580c}
.okall{background:#e9f8f0;border:1px solid #b3e3cb;color:#127045}
a.back{color:var(--azul-d);text-decoration:none;font-size:14px;font-weight:600}
.evt-link{color:var(--mut);font-size:13px;word-break:break-all}
.evt-link a{color:var(--azul-d)}
.err{background:#fdecee;border:1px solid #f3b8bf;color:#9b1c2a;border-radius:12px;padding:16px;
 white-space:pre-wrap;font-family:ui-monospace,monospace;font-size:12.5px}
.manual{margin-top:24px;background:#f3f7f9;border:1px solid var(--line);border-left:4px solid var(--azul);
 border-radius:13px;padding:18px 20px}
.manual h2{font-size:15.5px;margin:0 0 12px;color:var(--teal)}
.manual h2 span{font-weight:400;color:var(--mut);font-size:13px}
.manual ul{margin:0;padding-left:20px;line-height:1.8;font-size:14px}
.manual li{margin-bottom:4px}
.foot{margin-top:34px;text-align:center;color:var(--mut);font-size:12px}
.actions{display:flex;gap:10px;flex-wrap:wrap}
.actions .btn{margin-top:0}
.report{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:24px;
 box-shadow:0 1px 2px rgba(20,60,75,.04)}
.rep-head{display:flex;align-items:center;gap:18px;border-bottom:1px solid var(--line);
 padding-bottom:16px;margin-bottom:6px}
.rep-logo{height:34px}
.report h1{font-size:21px;margin:0}
.report .cards{margin:16px 0 6px}
h2.sec{font-size:15px;color:var(--teal);margin:26px 0 4px;padding-top:6px}
.sec-sub{font-size:13px;color:var(--mut);margin:0 0 10px;font-weight:600}
@media print{
 .noprint{display:none!important}
 body{background:#fff}
 .topbar{display:none}
 .report{border:0;box-shadow:none;padding:0}
 .wrap{padding:0}
}
"""

HEADER = (f'<div class=topbar><div class=in>'
          f'<img src="{LOGO}" alt="Ingresso Digital">'
          f'<span class=tag>Revisor de Cadastro de Eventos</span></div></div>')

FORM_HTML = """<!doctype html><html lang=pt-br><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Revisor de Cadastro · Ingresso Digital</title><style>{css}</style></head><body>
{header}
<div class=wrap>
<h1>Revisar cadastro</h1>
<p class=sub>Cole o cadastro que a produção enviou e o link do evento no ar. O sistema lê a
página de vendas e compara tudo, apontando divergências e o que precisa de conferência manual.</p>
<form method=post action=/revisar class=panel>
<label>Texto do cadastro</label>
<textarea name=cadastro placeholder="Show: ...&#10;Cidade: ...&#10;Data: ...&#10;Local: ...&#10;Horário: ...&#10;Valores / Setores: ...&#10;Taxa de conveniência: ...">{cadastro}</textarea>
<label>Link do evento no ar (página de vendas)</label>
<input type=text name=link placeholder="https://ingressodigital.com/evento/00000/slug-do-evento" value="{link}">
<button type=submit class="btn btn-primary">Revisar cadastro</button>
</form>
<div class=foot>Lê a página pública do Ingresso Digital · não armazena nenhum dado</div>
</div></body></html>"""


def _form(cadastro="", link="") -> bytes:
    return FORM_HTML.format(css=PAGE_CSS, header=HEADER,
                            cadastro=html.escape(cadastro),
                            link=html.escape(link)).encode("utf-8")


def _result_html(cadastro: str, link: str, res: dict) -> bytes:
    r = res["resumo"]
    cards = ""
    for key in ("ok", "divergente", "extra", "faltando", "info"):
        ico, cor, _lbl = STATUS_INFO[key]
        cards += (f'<div class=card><div class=n style="color:{cor}">{r[key]}</div>'
                  f'<div class=l>{ico} {_lbl}</div></div>')

    problemas = r["divergente"] + r["extra"] + r["faltando"]
    if problemas == 0:
        alerta = '<div class="alert okall">✅ Nenhuma divergência encontrada nos campos verificáveis. Confira os itens marcados como “Conferir”.</div>'
    else:
        alerta = (f'<div class=alert>⚠️ {problemas} ponto(s) de atenção: '
                  f'{r["divergente"]} divergência(s), {r["extra"]} setor(es) extra no site, '
                  f'{r["faltando"]} faltando. Revise abaixo.</div>')

    linhas = ""
    rowcls = {"divergente": "row-div", "extra": "row-extra", "faltando": "row-falt"}
    for c in res["checks"]:
        ico, cor, lbl = STATUS_INFO[c["status"]]
        obs = f'<div class=obs>{html.escape(c["obs"])}</div>' if c["obs"] else ""
        linhas += (
            f'<tr class="{rowcls.get(c["status"],"")}">'
            f'<td><span class=badge style="background:{cor}">{ico} {lbl}</span></td>'
            f'<td><b>{html.escape(c["campo"])}</b></td>'
            f'<td>{html.escape(c["cadastro"])}</td>'
            f'<td>{html.escape(c["site"])}{obs}</td></tr>'
        )

    # Ficha de itens obrigatórios (não podem faltar no evento no ar).
    ic_ficha = {"ok": ("✅", "var(--ok)", "OK"),
                "faltando": ("⚠️", "var(--falt)", "FALTANDO"),
                "info": ("ℹ️", "var(--info)", "Conferir")}
    frows = ""
    for f in res["ficha"]:
        ico, cor, lbl = ic_ficha[f["status"]]
        obs = f'<div class=obs>{html.escape(f["obs"])}</div>' if f.get("obs") else ""
        rc = "row-falt" if f["status"] == "faltando" else ""
        frows += (f'<tr class="{rc}"><td><span class=badge style="background:{cor}">{ico} {lbl}</span></td>'
                  f'<td><b>{html.escape(f["item"])}</b></td>'
                  f'<td>{html.escape(f["conteudo"])}{obs}</td></tr>')
    n_falta = sum(1 for f in res["ficha"] if f["status"] == "faltando")
    ficha_titulo = ("✅ Todos os itens obrigatórios estão no ar" if n_falta == 0
                    else f'⚠️ {n_falta} item(ns) obrigatório(s) faltando no ar')
    ficha_block = (
        f'<h2 class=sec>Itens obrigatórios do evento</h2>'
        f'<p class=sec-sub>{ficha_titulo}</p>'
        f'<table><thead><tr><th>Status</th><th>Item</th><th>Conteúdo no ar</th></tr></thead>'
        f'<tbody>{frows}</tbody></table>'
    )

    # Bloco dedicado: pontos que o site não expõe e precisam de conferência manual.
    manuais = [c for c in res["checks"] if c["status"] == "info"]
    if manuais:
        itens = ""
        for c in manuais:
            extra = f' — <span style="color:#9aa0aa">{html.escape(c["obs"])}</span>' if c["obs"] else ""
            itens += (f'<li><b>{html.escape(c["campo"])}:</b> '
                      f'{html.escape(c["cadastro"])}{extra}</li>')
        manual_block = (
            '<div class="manual"><h2>ℹ️ Conferir manualmente '
            '<span>(não aparece na página de vendas)</span></h2>'
            f'<ul>{itens}</ul></div>'
        )
    else:
        manual_block = ""

    nome = html.escape(res["site"].get("nome") or "—")
    body = f"""<!doctype html><html lang=pt-br><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Revisão · {nome}</title><style>{PAGE_CSS}</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
</head><body>
{HEADER}
<div class=wrap>
<div class="head-row noprint">
  <a class="btn btn-ghost" href="/">+ Novo evento</a>
  <div class=actions>
    <button class="btn btn-ghost" onclick="window.print()">🖨️ Imprimir / PDF</button>
    <button class="btn btn-primary" id=btnimg onclick="salvarImagem()">🖼️ Salvar como imagem</button>
  </div>
</div>
<div id=relatorio class=report>
  <div class=rep-head>
    <img src="{LOGO}" alt="Ingresso Digital" class=rep-logo>
    <div>
      <h1>{nome}</h1>
      <p class="evt-link">Página de vendas: <a href="{html.escape(link)}" target=_blank>{html.escape(link)}</a></p>
    </div>
  </div>
  {alerta}
  <div class=cards>{cards}</div>
  {ficha_block}
  <h2 class=sec>Conferência cadastro × site</h2>
  <table><thead><tr><th>Status</th><th>Campo</th><th>Cadastro</th><th>No ar (site)</th></tr></thead>
  <tbody>{linhas}</tbody></table>
  {manual_block}
</div>
<div class=foot><a class=back href="/">+ Revisar outro evento</a></div>
</div>
<script>
function salvarImagem(){{
  var btn=document.getElementById('btnimg'); var txt=btn.textContent; btn.textContent='Gerando...';
  var alvo=document.getElementById('relatorio');
  html2canvas(alvo,{{backgroundColor:'#ffffff',scale:2,useCORS:true}}).then(function(canvas){{
    var a=document.createElement('a');
    a.download='revisao-{nome}.png'.replace(/[^a-z0-9.-]+/gi,'_');
    a.href=canvas.toDataURL('image/png'); a.click(); btn.textContent=txt;
  }}).catch(function(e){{alert('Não consegui gerar a imagem. Use Imprimir / PDF.');btn.textContent=txt;}});
}}
</script>
</body></html>"""
    return body.encode("utf-8")


def _error_html(msg: str) -> bytes:
    body = (f"<!doctype html><meta charset=utf-8><style>{PAGE_CSS}</style>{HEADER}"
            f"<div class=wrap><a class='btn btn-ghost' href='/'>+ Novo evento</a>"
            f"<h1 style='margin-top:16px'>Não consegui revisar</h1>"
            f"<p class=sub>Verifique se o link é de um evento do Ingresso Digital "
            f"(formato .../evento/00000/nome).</p>"
            f"<div class=err>{html.escape(msg)}</div></div>")
    return body.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(_form())
        elif self.path == "/logo.svg":
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Cache-Control", "public, max-age=86400")
            self.send_header("Content-Length", str(len(LOGO_SVG)))
            self.end_headers()
            self.wfile.write(LOGO_SVG)
        else:
            self._send(b"not found", 404)

    def do_POST(self):
        if self.path != "/revisar":
            self._send(b"not found", 404)
            return
        length = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(length).decode("utf-8")
        form = parse_qs(data, keep_blank_values=True)
        cadastro = (form.get("cadastro", [""])[0]).strip()
        link = (form.get("link", [""])[0]).strip()
        if not cadastro or not link:
            self._send(_error_html("Preencha o cadastro e o link."))
            return
        try:
            res = revisar_safe(cadastro, link)
            self._send(_result_html(cadastro, link, res))
        except Exception:
            self._send(_error_html(traceback.format_exc()))

    def log_message(self, *args):
        pass  # silencia o log padrão


def revisar_safe(cadastro: str, link: str) -> dict:
    return revisor.revisar(cadastro, link)


def main():
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Revisor de Cadastro rodando em  http://localhost:{PORT}")
    print("Ctrl+C para parar.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrado.")


if __name__ == "__main__":
    main()
