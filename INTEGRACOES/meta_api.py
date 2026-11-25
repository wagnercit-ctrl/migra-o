"""
Integracao Meta (Facebook + Instagram) da Carla Nunes Estetica Negra.

SOMENTE LEITURA. Nada aqui pausa, ativa ou altera campanha.

Le do config/.env:
  META_ACCESS_TOKEN   token de System User (permanente) do Business da clinica
                      ou do Business parceiro que recebeu acesso aos ativos
  META_AD_ACCOUNT     conta de anuncio, ex: act_1234567890
  META_PAGE_ID        id da pagina do Facebook da clinica
  META_IG_USER_ID     id da conta profissional do Instagram (opcional: se vazio,
                      e descoberto pela pagina)

Blocos que o painel usa:
  anuncios(periodo)      -> totais, serie diaria, campanhas, anuncios, publico
  instagram(periodo)     -> perfil, metricas do periodo, ultimos posts
  pagina()               -> seguidores da pagina do Facebook
  leads_formulario()     -> formularios de Lead Ads e os leads mais recentes

Cada bloco devolve {'ok': False, 'erro': '...'} quando a Meta recusa, para o
painel mostrar o motivo em vez de quebrar.
"""
import json
import logging
import os
from datetime import date, timedelta

import requests

log = logging.getLogger('meta_api')

VERSAO = 'v21.0'
BASE = f'https://graph.facebook.com/{VERSAO}'

# --- o que conta como lead numa clinica -------------------------------------
# conversa iniciada no WhatsApp / Direct / Messenger a partir do anuncio
ACAO_CONVERSA = 'onsite_conversion.messaging_conversation_started_7d'
# formulario instantaneo (Lead Ads) - a Meta usa um destes nomes
ACOES_FORMULARIO = ('onsite_conversion.lead_grouped', 'leadgen_grouped')
# lead marcado pelo pixel no site (agendamento online, por exemplo)
ACAO_LEAD_SITE = 'offsite_conversion.fb_pixel_lead'

CAMPOS_INSIGHTS = ('spend,impressions,reach,clicks,inline_link_clicks,ctr,cpc,cpm,'
                   'frequency,actions')


class ErroMeta(Exception):
    pass


# ============================================================
# BASICO
# ============================================================

def carregar_env(caminho=None):
    """Carrega config/.env para os.environ (sem sobrescrever o que ja existe)."""
    caminho = caminho or os.path.join(os.path.dirname(__file__), '..', 'config', '.env')
    if not os.path.exists(caminho):
        return False
    for linha in open(caminho, encoding='utf-8', errors='ignore'):
        linha = linha.strip()
        if '=' in linha and not linha.startswith('#'):
            k, v = linha.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return True


def cfg(nome, padrao=''):
    return (os.getenv(nome) or padrao).strip()


def _get(caminho, params=None, token=None):
    token = token or cfg('META_ACCESS_TOKEN')
    if not token:
        raise ErroMeta('META_ACCESS_TOKEN vazio no config/.env')
    params = dict(params or {})
    params['access_token'] = token
    try:
        r = requests.get(f'{BASE}/{caminho}', params=params, timeout=60)
    except requests.RequestException as e:
        raise ErroMeta(f'sem conexao com a Meta: {e}')
    dados = r.json() if r.content else {}
    if r.status_code != 200 or 'error' in dados:
        msg = (dados.get('error') or {}).get('message') or r.text[:200]
        raise ErroMeta(f'{caminho}: {msg}')
    return dados


def _get_paginado(caminho, params=None, token=None, limite_itens=500):
    """Segue o 'paging.next' ate juntar limite_itens."""
    itens = []
    d = _get(caminho, params, token)
    while True:
        itens.extend(d.get('data', []))
        prox = (d.get('paging') or {}).get('next')
        if not prox or len(itens) >= limite_itens:
            break
        r = requests.get(prox, timeout=60)
        d = r.json() if r.content else {}
        if 'error' in d:
            break
    return itens[:limite_itens]


def _bloco(func):
    """Decorator: transforma ErroMeta em {'ok': False, 'erro': ...}."""
    def envolto(*a, **kw):
        try:
            res = func(*a, **kw)
            res['ok'] = True
            return res
        except ErroMeta as e:
            log.warning(f'{func.__name__}: {e}')
            return {'ok': False, 'erro': str(e)}
    envolto.__name__ = func.__name__
    return envolto


# ============================================================
# PERIODOS
# ============================================================

PERIODOS = {
    '7d': 'Ultimos 7 dias',
    '30d': 'Ultimos 30 dias',
    'mes': 'Mes atual',
    'mes_passado': 'Mes passado',
}


def intervalo(periodo, hoje=None):
    """(inicio, fim, inicio_anterior, fim_anterior) do periodo, em date."""
    hoje = hoje or date.today()
    ontem = hoje - timedelta(days=1)
    if periodo == '7d':
        ini, fim = ontem - timedelta(days=6), ontem
    elif periodo == '30d':
        ini, fim = ontem - timedelta(days=29), ontem
    elif periodo == 'mes':
        ini, fim = hoje.replace(day=1), hoje
    elif periodo == 'mes_passado':
        fim = hoje.replace(day=1) - timedelta(days=1)
        ini = fim.replace(day=1)
    else:
        raise ValueError(f'periodo desconhecido: {periodo}')
    dias = (fim - ini).days + 1
    fim_ant = ini - timedelta(days=1)
    ini_ant = fim_ant - timedelta(days=dias - 1)
    return ini, fim, ini_ant, fim_ant


def _time_range(ini, fim):
    return json.dumps({'since': ini.isoformat(), 'until': fim.isoformat()})


# ============================================================
# LEITURA DAS ACOES
# ============================================================

def _acao(actions, tipo):
    for a in actions or []:
        if a.get('action_type') == tipo:
            return int(float(a.get('value', 0)))
    return 0


def leads_da_linha(linha):
    """Quebra os leads de uma linha de insights em conversa / formulario / site."""
    acts = linha.get('actions')
    form = 0
    for t in ACOES_FORMULARIO:
        form = _acao(acts, t)
        if form:
            break
    conv = _acao(acts, ACAO_CONVERSA)
    site = _acao(acts, ACAO_LEAD_SITE)
    return {'conversas': conv, 'formularios': form, 'site': site,
            'total': conv + form + site}


def _resumir(linha):
    gasto = float(linha.get('spend', 0) or 0)
    leads = leads_da_linha(linha)
    return {
        'gasto': round(gasto, 2),
        'impressoes': int(linha.get('impressions', 0) or 0),
        'alcance': int(linha.get('reach', 0) or 0),
        'cliques': int(linha.get('inline_link_clicks', 0) or linha.get('clicks', 0) or 0),
        'ctr': round(float(linha.get('ctr', 0) or 0), 2),
        'cpc': round(float(linha.get('cpc', 0) or 0), 2),
        'cpm': round(float(linha.get('cpm', 0) or 0), 2),
        'frequencia': round(float(linha.get('frequency', 0) or 0), 2),
        'leads': leads,
        'cpl': round(gasto / leads['total'], 2) if leads['total'] else None,
    }


def _insights(conta, ini, fim, **extra):
    params = {'fields': CAMPOS_INSIGHTS, 'time_range': _time_range(ini, fim), 'limit': 500}
    params.update(extra)
    return _get_paginado(f'{conta}/insights', params)


# ============================================================
# ANUNCIOS
# ============================================================

@_bloco
def anuncios(periodo):
    conta = cfg('META_AD_ACCOUNT')
    if not conta:
        raise ErroMeta('META_AD_ACCOUNT vazio no config/.env')
    if not conta.startswith('act_'):
        conta = 'act_' + conta
    ini, fim, ini_a, fim_a = intervalo(periodo)

    total = _insights(conta, ini, fim)
    anterior = _insights(conta, ini_a, fim_a)
    diario = _insights(conta, ini, fim, time_increment=1)

    # campanhas: insights + status/orcamento
    linhas_camp = _insights(conta, ini, fim, level='campaign',
                            fields=CAMPOS_INSIGHTS + ',campaign_id,campaign_name')
    info_camp = {c['id']: c for c in _get_paginado(f'{conta}/campaigns', {
        'fields': 'name,effective_status,objective,daily_budget,lifetime_budget', 'limit': 200})}
    campanhas = []
    for l in linhas_camp:
        c = info_camp.get(l.get('campaign_id'), {})
        orc = c.get('daily_budget')
        campanhas.append({
            'id': l.get('campaign_id'),
            'nome': l.get('campaign_name'),
            'status': c.get('effective_status', '-'),
            'objetivo': c.get('objective', '-'),
            'orcamento_diario': round(int(orc) / 100, 2) if orc else None,
            **_resumir(l),
        })
    # campanhas ativas sem entrega no periodo tambem aparecem
    vistas = {c['id'] for c in campanhas}
    for cid, c in info_camp.items():
        if cid not in vistas and c.get('effective_status') == 'ACTIVE':
            campanhas.append({'id': cid, 'nome': c.get('name'), 'status': 'ACTIVE',
                              'objetivo': c.get('objective', '-'),
                              'orcamento_diario': None, **_resumir({})})
    campanhas.sort(key=lambda x: -x['gasto'])

    # anuncios (criativos) com miniatura
    linhas_ad = _insights(conta, ini, fim, level='ad',
                          fields=CAMPOS_INSIGHTS + ',ad_id,ad_name,campaign_name')
    thumbs = {}
    try:
        for a in _get_paginado(f'{conta}/ads', {
                'fields': 'effective_status,creative{thumbnail_url,image_url}', 'limit': 200}):
            cr = a.get('creative') or {}
            thumbs[a['id']] = (cr.get('thumbnail_url') or cr.get('image_url') or '',
                               a.get('effective_status', '-'))
    except ErroMeta:
        pass
    ads = []
    for l in linhas_ad:
        th, st = thumbs.get(l.get('ad_id'), ('', '-'))
        ads.append({'id': l.get('ad_id'), 'nome': l.get('ad_name'),
                    'campanha': l.get('campaign_name'), 'status': st, 'miniatura': th,
                    **_resumir(l)})
    ads.sort(key=lambda x: (x['cpl'] is None, x['cpl'] or 0, -x['gasto']))

    # publico
    def quebra(breakdowns):
        try:
            return _insights(conta, ini, fim, breakdowns=breakdowns,
                             fields='spend,impressions,reach,actions')
        except ErroMeta:
            return []
    idade_genero = [{'idade': l.get('age'), 'genero': l.get('gender'),
                     'gasto': round(float(l.get('spend', 0) or 0), 2),
                     'alcance': int(l.get('reach', 0) or 0),
                     'leads': leads_da_linha(l)['total']} for l in quebra('age,gender')]
    regioes = sorted([{'regiao': l.get('region'),
                       'gasto': round(float(l.get('spend', 0) or 0), 2),
                       'alcance': int(l.get('reach', 0) or 0),
                       'leads': leads_da_linha(l)['total']} for l in quebra('region')],
                     key=lambda x: -x['gasto'])[:12]
    posicionamentos = sorted([{'plataforma': l.get('publisher_platform'),
                               'posicao': l.get('platform_position'),
                               'gasto': round(float(l.get('spend', 0) or 0), 2),
                               'leads': leads_da_linha(l)['total']}
                              for l in quebra('publisher_platform,platform_position')],
                             key=lambda x: -x['gasto'])

    return {
        'periodo': {'inicio': ini.isoformat(), 'fim': fim.isoformat(),
                    'inicio_anterior': ini_a.isoformat(), 'fim_anterior': fim_a.isoformat()},
        'total': _resumir(total[0] if total else {}),
        'anterior': _resumir(anterior[0] if anterior else {}),
        'diario': [{'data': l.get('date_start'), **_resumir(l)} for l in diario],
        'campanhas': campanhas,
        'anuncios': ads[:30],
        'publico': {'idade_genero': idade_genero, 'regioes': regioes,
                    'posicionamentos': posicionamentos},
    }


# ============================================================
# PAGINA E INSTAGRAM
# ============================================================

_cache_pagina = {}


def _token_da_pagina():
    """Token da pagina (necessario para leads e algumas leituras)."""
    pid = cfg('META_PAGE_ID')
    if not pid:
        return None
    if 'token' not in _cache_pagina:
        try:
            d = _get(pid, {'fields': 'access_token'})
            _cache_pagina['token'] = d.get('access_token')
        except ErroMeta:
            _cache_pagina['token'] = None
    return _cache_pagina['token']


def ig_user_id():
    ig = cfg('META_IG_USER_ID')
    if ig:
        return ig
    pid = cfg('META_PAGE_ID')
    if not pid:
        raise ErroMeta('META_IG_USER_ID e META_PAGE_ID vazios no config/.env')
    d = _get(pid, {'fields': 'instagram_business_account'})
    ig = (d.get('instagram_business_account') or {}).get('id')
    if not ig:
        raise ErroMeta('a pagina nao tem conta profissional do Instagram vinculada')
    os.environ['META_IG_USER_ID'] = ig
    return ig


@_bloco
def pagina():
    pid = cfg('META_PAGE_ID')
    if not pid:
        raise ErroMeta('META_PAGE_ID vazio no config/.env')
    d = _get(pid, {'fields': 'name,fan_count,followers_count,link'})
    return {'nome': d.get('name'), 'curtidas': d.get('fan_count'),
            'seguidores': d.get('followers_count'), 'link': d.get('link')}


def _metrica_total(ig, metrica, ini, fim):
    """Soma de uma metrica de conta no intervalo (a Meta aceita no maximo 30 dias)."""
    try:
        d = _get(f'{ig}/insights', {
            'metric': metrica, 'period': 'day', 'metric_type': 'total_value',
            'since': ini.isoformat(), 'until': (fim + timedelta(days=1)).isoformat()})
    except ErroMeta:
        return None
    for m in d.get('data', []):
        tv = m.get('total_value') or {}
        if 'value' in tv:
            return tv['value']
    return None


@_bloco
def instagram(periodo):
    ig = ig_user_id()
    ini, fim, ini_a, fim_a = intervalo(periodo)
    perfil = _get(ig, {'fields': 'username,name,followers_count,follows_count,media_count,'
                                 'profile_picture_url'})
    metricas = {}
    anteriores = {}
    for m in ('reach', 'accounts_engaged', 'total_interactions', 'profile_views',
              'website_clicks', 'follows_and_unfollows'):
        metricas[m] = _metrica_total(ig, m, ini, fim)
        anteriores[m] = _metrica_total(ig, m, ini_a, fim_a)

    # seguidores novos por dia (a Meta so devolve os ultimos 30 dias)
    seguidores_dia = []
    try:
        d = _get(f'{ig}/insights', {'metric': 'follower_count', 'period': 'day',
                                    'since': max(ini, date.today() - timedelta(days=29)).isoformat(),
                                    'until': (fim + timedelta(days=1)).isoformat()})
        for m in d.get('data', []):
            for v in m.get('values', []):
                seguidores_dia.append({'data': v.get('end_time', '')[:10], 'novos': v.get('value', 0)})
    except ErroMeta:
        pass

    posts = []
    for p in _get_paginado(f'{ig}/media', {
            'fields': 'caption,media_type,media_product_type,permalink,thumbnail_url,media_url,'
                      'timestamp,like_count,comments_count', 'limit': 50}, limite_itens=50):
        dia = p.get('timestamp', '')[:10]
        if dia and not (ini.isoformat() <= dia <= fim.isoformat()):
            continue
        ins = {}
        metricas_post = 'reach,saved,shares,total_interactions'
        if p.get('media_product_type') == 'REELS':
            metricas_post += ',views'
        try:
            for m in _get(f"{p['id']}/insights", {'metric': metricas_post}).get('data', []):
                ins[m['name']] = (m.get('values') or [{}])[0].get('value', 0)
        except ErroMeta:
            pass
        formato = 'Reels' if p.get('media_product_type') == 'REELS' else {
            'CAROUSEL_ALBUM': 'Carrossel', 'VIDEO': 'Video', 'IMAGE': 'Imagem'}.get(p.get('media_type'), '-')
        posts.append({
            'data': dia, 'formato': formato, 'link': p.get('permalink'),
            'miniatura': p.get('thumbnail_url') or p.get('media_url') or '',
            'legenda': (p.get('caption') or '')[:140],
            'curtidas': p.get('like_count', 0), 'comentarios': p.get('comments_count', 0),
            'alcance': ins.get('reach'), 'salvos': ins.get('saved'),
            'compartilhamentos': ins.get('shares'), 'interacoes': ins.get('total_interactions'),
            'visualizacoes': ins.get('views'),
        })

    return {
        'perfil': {'usuario': perfil.get('username'), 'nome': perfil.get('name'),
                   'seguidores': perfil.get('followers_count'),
                   'seguindo': perfil.get('follows_count'), 'posts': perfil.get('media_count'),
                   'foto': perfil.get('profile_picture_url')},
        'metricas': metricas, 'anteriores': anteriores,
        'seguidores_dia': seguidores_dia, 'posts': posts,
    }


@_bloco
def leads_formulario(limite=40):
    pid = cfg('META_PAGE_ID')
    if not pid:
        raise ErroMeta('META_PAGE_ID vazio no config/.env')
    tok = _token_da_pagina()
    forms = _get_paginado(f'{pid}/leadgen_forms',
                          {'fields': 'id,name,status,leads_count', 'limit': 50}, token=tok)
    leads = []
    for f in forms:
        if f.get('status') != 'ACTIVE' and not f.get('leads_count'):
            continue
        try:
            for l in _get_paginado(f"{f['id']}/leads", {
                    'fields': 'created_time,field_data,ad_name,campaign_name', 'limit': 50},
                    token=tok, limite_itens=limite):
                campos = {c['name']: ', '.join(c.get('values', [])) for c in l.get('field_data', [])}
                leads.append({'data': l.get('created_time', '')[:16].replace('T', ' '),
                              'formulario': f.get('name'), 'campanha': l.get('campaign_name'),
                              'anuncio': l.get('ad_name'), 'campos': campos})
        except ErroMeta:
            continue
    leads.sort(key=lambda x: x['data'], reverse=True)
    return {'formularios': [{'nome': f.get('name'), 'status': f.get('status'),
                             'total': f.get('leads_count')} for f in forms],
            'leads': leads[:limite]}


def diagnostico():
    """O que o token enxerga. Usado por 'python painel/gerar_painel.py --testar'."""
    out = {}
    for nome, cam, campos in (('contas_anuncio', 'me/adaccounts', 'name,account_id,account_status'),
                              ('paginas', 'me/accounts', 'name,id,instagram_business_account')):
        try:
            out[nome] = _get_paginado(cam, {'fields': campos, 'limit': 100})
        except ErroMeta as e:
            out[nome] = f'ERRO: {e}'
    return out
