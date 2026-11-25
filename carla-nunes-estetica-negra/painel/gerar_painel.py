"""
Gera o painel da Carla Nunes Estetica Negra.

  python painel/gerar_painel.py            puxa tudo da Meta e gera painel/saida/painel.html
  python painel/gerar_painel.py --demo     gera com dados ficticios (para mostrar antes do acesso)
  python painel/gerar_painel.py --abrir    gera e abre no navegador
  python painel/gerar_painel.py --resumo   imprime o resumo de ontem/7 dias em texto (WhatsApp)
  python painel/gerar_painel.py --testar   mostra o que o token enxerga (contas, paginas)

Saida: painel/saida/painel.html (arquivo unico, abre offline) e painel/saida/dados.json.
"""
import argparse
import json
import os
import sys
import webbrowser
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, os.path.join(RAIZ, 'INTEGRACOES'))
sys.path.insert(0, AQUI)

import meta_api as meta  # noqa: E402

SAIDA = os.path.join(AQUI, 'saida')
TEMPLATE = os.path.join(AQUI, 'template.html')


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _var(atual, anterior):
    a, b = _num(atual), _num(anterior)
    if a is None or not b:
        return None
    return round((a - b) / b * 100, 1)


# ============================================================
# ALERTAS (regras simples, explicaveis para a clinica)
# ============================================================

def alertas(ads, ig, metas, periodo=''):
    out = []
    if ads.get('ok'):
        t, ant = ads['total'], ads['anterior']
        cpl_conta = t['cpl']
        alvo = metas.get('cpl_alvo')
        if cpl_conta and alvo and cpl_conta > alvo:
            out.append(('atencao', f'Custo por lead em R$ {cpl_conta:.2f}, acima da meta de R$ {alvo:.2f}.'))
        v = _var(t['cpl'], ant['cpl'])
        if v is not None and v >= 25:
            out.append(('atencao', f'Custo por lead subiu {v:.0f}% contra o periodo anterior.'))
        elif v is not None and v <= -15:
            out.append(('bom', f'Custo por lead caiu {abs(v):.0f}% contra o periodo anterior.'))
        for c in ads['campanhas']:
            if c['status'] != 'ACTIVE':
                continue
            nome = c['nome']
            if c['gasto'] > 0 and c['leads']['total'] == 0 and cpl_conta and c['gasto'] >= cpl_conta * 2:
                out.append(('critico', f'"{nome}" gastou R$ {c["gasto"]:.2f} sem gerar nenhum lead.'))
            elif c['cpl'] and cpl_conta and c['cpl'] > cpl_conta * 1.5 and c['gasto'] >= cpl_conta * 2:
                out.append(('atencao', f'"{nome}" esta com lead a R$ {c["cpl"]:.2f}, '
                                       f'{c["cpl"] / cpl_conta:.1f}x a media da conta. Revisar criativo ou publico.'))
            if c['frequencia'] >= 3.5:
                out.append(('atencao', f'"{nome}" com frequencia {c["frequencia"]:.1f}: o mesmo publico esta '
                                       f'vendo o anuncio muitas vezes. Hora de trocar o criativo.'))
            if c['impressoes'] > 2000 and c['ctr'] < 0.8:
                out.append(('atencao', f'"{nome}" com CTR de {c["ctr"]:.2f}%: o anuncio chama pouca atencao.'))
        melhores = [a for a in ads['anuncios'] if a['cpl'] and a['leads']['total'] >= 3]
        if melhores:
            m = min(melhores, key=lambda a: a['cpl'])
            out.append(('bom', f'Melhor anuncio: "{m["nome"]}", {m["leads"]["total"]} leads a R$ {m["cpl"]:.2f} cada.'))
        orc = metas.get('orcamento_mensal')
        if orc and periodo in ('mes', 'mes_passado') and t['gasto'] > orc:
            out.append(('atencao', f'Investimento do periodo (R$ {t["gasto"]:.2f}) passou do orcamento mensal de R$ {orc:.2f}.'))
    if ig.get('ok') and ig['posts']:
        por_formato = {}
        for p in ig['posts']:
            if p['alcance'] is not None:
                por_formato.setdefault(p['formato'], []).append(p['alcance'])
        medias = {f: sum(v) / len(v) for f, v in por_formato.items() if len(v) >= 2}
        if len(medias) >= 2:
            melhor = max(medias, key=medias.get)
            pior = min(medias, key=medias.get)
            if medias[pior] and medias[melhor] / medias[pior] >= 1.5:
                out.append(('bom', f'No Instagram, {melhor} alcanca em media {medias[melhor] / medias[pior]:.1f}x '
                                   f'mais que {pior}. Vale postar mais nesse formato.'))
    return [{'nivel': n, 'texto': t} for n, t in out]


# ============================================================
# COLETA
# ============================================================

def coletar():
    meta.carregar_env()
    metas = {'cpl_alvo': _num(meta.cfg('META_CPL_ALVO')),
             'orcamento_mensal': _num(meta.cfg('META_ORCAMENTO_MENSAL'))}
    pag = meta.pagina()
    leads = meta.leads_formulario()
    periodos = {}
    for p in meta.PERIODOS:
        print(f'  puxando {meta.PERIODOS[p].lower()}...')
        a = meta.anuncios(p)
        i = meta.instagram(p)
        periodos[p] = {'rotulo': meta.PERIODOS[p], 'anuncios': a, 'instagram': i,
                       'alertas': alertas(a, i, metas, p)}
    return {'demo': False, 'pagina': pag, 'leads_formulario': leads, 'periodos': periodos,
            'metas': metas}


def montar(dados):
    dados['clinica'] = os.getenv('CLINICA_NOME') or 'Carla Nunes Estetica Negra'
    dados['gerado_em'] = datetime.now().strftime('%d/%m/%Y %H:%M')
    os.makedirs(SAIDA, exist_ok=True)
    with open(os.path.join(SAIDA, 'dados.json'), 'w', encoding='utf-8') as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)
    html = open(TEMPLATE, encoding='utf-8').read()
    carga = json.dumps(dados, ensure_ascii=False).replace('</', '<\\/')
    html = html.replace('/*__DADOS__*/null', carga)
    destino = os.path.join(SAIDA, 'painel.html')
    with open(destino, 'w', encoding='utf-8') as f:
        f.write(html)
    return destino


# ============================================================
# RESUMO EM TEXTO
# ============================================================

def _brl(v):
    if v is None:
        return '-'
    return 'R$ ' + f'{v:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def resumo_texto(dados, periodo='7d'):
    p = dados['periodos'][periodo]
    a, i = p['anuncios'], p['instagram']
    linhas = [f"*{dados['clinica']}* - {p['rotulo'].lower()}"]
    if a.get('ok'):
        t = a['total']
        linhas += ['', '*Anuncios*',
                   f"Investido: {_brl(t['gasto'])}",
                   f"Leads: {t['leads']['total']} ({t['leads']['conversas']} conversas, "
                   f"{t['leads']['formularios']} formularios, {t['leads']['site']} pelo site)",
                   f"Custo por lead: {_brl(t['cpl'])}",
                   f"Alcance: {t['alcance']:,}".replace(',', '.')]
    else:
        linhas += ['', f"Anuncios: sem acesso ({a.get('erro')})"]
    if i.get('ok'):
        m = i['metricas']
        linhas += ['', '*Instagram*',
                   f"Seguidores: {i['perfil']['seguidores']}",
                   f"Alcance: {m.get('reach') or '-'}  |  Visitas ao perfil: {m.get('profile_views') or '-'}",
                   f"Posts no periodo: {len(i['posts'])}"]
    if p['alertas']:
        linhas += ['', '*Pontos de atencao*'] + [f"- {x['texto']}" for x in p['alertas'][:5]]
    return '\n'.join(linhas)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--demo', action='store_true')
    ap.add_argument('--abrir', action='store_true')
    ap.add_argument('--resumo', action='store_true')
    ap.add_argument('--testar', action='store_true')
    args = ap.parse_args()

    if args.testar:
        meta.carregar_env()
        print(json.dumps(meta.diagnostico(), ensure_ascii=False, indent=2))
        return

    if args.demo:
        import demo
        dados = demo.gerar()
        for chave, p in dados['periodos'].items():
            p['alertas'] = alertas(p['anuncios'], p['instagram'], dados['metas'], chave)
    else:
        print('Puxando dados da Meta...')
        dados = coletar()

    destino = montar(dados)
    print(f'Painel gerado: {destino}')
    if args.resumo:
        print()
        print(resumo_texto(dados))
    if args.abrir:
        webbrowser.open('file:///' + destino.replace('\\', '/'))


if __name__ == '__main__':
    main()
