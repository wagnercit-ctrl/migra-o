"""
Dados FICTICIOS para mostrar o painel antes da clinica liberar o acesso a Meta.
O painel exibe uma faixa "DEMONSTRACAO" sempre que estes dados estao em uso.
"""
import random
from datetime import timedelta

import meta_api as meta

CAMPANHAS = [
    # nome, objetivo, orcamento/dia, cpl base, ctr base, frequencia, status
    ('Manchas e Melasma - WhatsApp', 'OUTCOME_ENGAGEMENT', 40, 9.5, 1.9, 2.1, 'ACTIVE'),
    ('Depilacao a Laser Pele Negra - WhatsApp', 'OUTCOME_ENGAGEMENT', 35, 12.8, 1.5, 2.6, 'ACTIVE'),
    ('Limpeza de Pele Profunda - Formulario', 'OUTCOME_LEADS', 25, 7.9, 1.7, 1.8, 'ACTIVE'),
    ('Peeling e Uniformizacao - WhatsApp', 'OUTCOME_ENGAGEMENT', 20, 21.4, 0.7, 3.9, 'ACTIVE'),
    ('Remarketing Instagram - Seguidores', 'OUTCOME_ENGAGEMENT', 15, 15.2, 1.2, 4.4, 'ACTIVE'),
    ('Black Friday Pacotes', 'OUTCOME_ENGAGEMENT', 0, 10.4, 2.3, 1.6, 'PAUSED'),
]

ANUNCIOS = {
    0: ['Video depoimento - antes e depois', 'Carrossel - 3 sessoes', 'Reels Dra. Carla explica o melasma'],
    1: ['Video - laser seguro para pele negra', 'Imagem - pacote 6 sessoes'],
    2: ['Reels - limpeza passo a passo', 'Imagem - agenda aberta'],
    3: ['Imagem - pele uniforme', 'Video - peeling sem manchar'],
    4: ['Carrossel - resultados reais'],
    5: ['Video - pacotes Black Friday'],
}

POSTS = [
    ('Reels', 'Melasma em pele negra tem tratamento. Te conto o que funciona e o que mancha.'),
    ('Carrossel', '5 cuidados antes do laser na pele retinta'),
    ('Imagem', 'Agenda de dezembro aberta. Garanta seu horario.'),
    ('Reels', 'Antes e depois: 4 sessoes de uniformizacao'),
    ('Carrossel', 'Mitos sobre peeling na pele negra'),
    ('Reels', 'Um dia na clinica com a Carla'),
    ('Imagem', 'Depoimento da cliente Ana'),
    ('Reels', 'Protetor solar em pele negra: precisa sim'),
    ('Carrossel', 'Rotina de skincare noturna em 4 passos'),
    ('Imagem', 'Pacote limpeza + hidratacao'),
]

NOMES = ['Juliana S.', 'Patricia M.', 'Fernanda O.', 'Camila R.', 'Aline T.', 'Bianca L.',
         'Renata C.', 'Tatiane F.', 'Priscila A.', 'Daniela B.', 'Simone G.', 'Larissa P.']
PROCED = ['Limpeza de pele', 'Tratamento de manchas', 'Depilacao a laser', 'Peeling']


def _linha(gasto, cpl, ctr, freq, rnd, tipo='conversa'):
    leads = int(round(gasto / cpl * rnd.uniform(0.85, 1.15))) if gasto and cpl else 0
    cpm = rnd.uniform(14, 22)
    imp = int(gasto / cpm * 1000) if gasto else 0
    cliques = int(imp * ctr / 100)
    alcance = int(imp / freq) if freq else 0
    conv, form, site = (leads, 0, 0) if tipo == 'conversa' else (0, leads, 0)
    if tipo == 'conversa' and leads > 4:
        site = rnd.randint(0, 2)
    tot = conv + form + site
    return {
        'gasto': round(gasto, 2), 'impressoes': imp, 'alcance': alcance, 'cliques': cliques,
        'ctr': round(ctr, 2) if gasto else 0, 'cpc': round(gasto / cliques, 2) if cliques else 0,
        'cpm': round(cpm, 2), 'frequencia': round(freq, 2),
        'leads': {'conversas': conv, 'formularios': form, 'site': site, 'total': tot},
        'cpl': round(gasto / tot, 2) if tot else None,
    }


def _soma(linhas):
    g = sum(l['gasto'] for l in linhas)
    imp = sum(l['impressoes'] for l in linhas)
    alc = int(sum(l['alcance'] for l in linhas) * 0.78)
    cli = sum(l['cliques'] for l in linhas)
    leads = {k: sum(l['leads'][k] for l in linhas) for k in ('conversas', 'formularios', 'site', 'total')}
    return {'gasto': round(g, 2), 'impressoes': imp, 'alcance': alc, 'cliques': cli,
            'ctr': round(cli / imp * 100, 2) if imp else 0, 'cpc': round(g / cli, 2) if cli else 0,
            'cpm': round(g / imp * 1000, 2) if imp else 0,
            'frequencia': round(imp / alc, 2) if alc else 0, 'leads': leads,
            'cpl': round(g / leads['total'], 2) if leads['total'] else None}


def _anuncios_bloco(periodo, rnd, fator_ant=1.0):
    ini, fim, ini_a, fim_a = meta.intervalo(periodo)
    dias = (fim - ini).days + 1

    campanhas, ads, diario_por_dia = [], [], {}
    for idx, (nome, obj, orc, cpl, ctr, freq, st) in enumerate(CAMPANHAS):
        ativo_dias = dias if st == 'ACTIVE' else (min(dias, 4) if periodo == 'mes_passado' else 0)
        gasto = orc * ativo_dias * rnd.uniform(0.92, 1.0) if orc else (60 * ativo_dias)
        tipo = 'formulario' if obj == 'OUTCOME_LEADS' else 'conversa'
        l = _linha(gasto, cpl, ctr * rnd.uniform(0.9, 1.1), freq, rnd, tipo)
        campanhas.append({'id': f'demo_c{idx}', 'nome': nome, 'status': st, 'objetivo': obj,
                          'orcamento_diario': orc or None, **l})
        if not gasto:
            continue
        pesos = [rnd.uniform(0.5, 1.5) for _ in ANUNCIOS[idx]]
        for nome_ad, p in zip(ANUNCIOS[idx], pesos):
            g = gasto * p / sum(pesos)
            ads.append({'id': f'demo_a{idx}{nome_ad[:3]}', 'nome': nome_ad, 'campanha': nome,
                        'status': st, 'miniatura': '',
                        **_linha(g, cpl * rnd.uniform(0.7, 1.4), ctr * rnd.uniform(0.8, 1.2), freq, rnd, tipo)})
    campanhas.sort(key=lambda c: -c['gasto'])
    ads.sort(key=lambda x: (x['cpl'] is None, x['cpl'] or 0))
    total = _soma([c for c in campanhas if c['gasto']])

    diario = []
    for d in range(dias):
        dia = ini + timedelta(days=d)
        fator = 1.18 if dia.weekday() in (0, 1) else (0.8 if dia.weekday() == 6 else 1.0)
        g = total['gasto'] / dias * rnd.uniform(0.9, 1.1)
        diario.append({'data': dia.isoformat(),
                       **_linha(g, (total['cpl'] or 12) / fator, total['ctr'], 1.1, rnd)})

    ant = dict(total)
    ant = {**ant, 'gasto': round(total['gasto'] * 0.94, 2)}
    lt = int(total['leads']['total'] * 0.86 * fator_ant)
    ant['leads'] = {'conversas': int(lt * 0.8), 'formularios': lt - int(lt * 0.8), 'site': 0, 'total': lt}
    ant['cpl'] = round(ant['gasto'] / lt, 2) if lt else None
    ant['alcance'] = int(total['alcance'] * 0.9)
    ant['ctr'] = round(total['ctr'] * 0.95, 2)

    faixas = ['18-24', '25-34', '35-44', '45-54', '55-64']
    pesos_f = [0.12, 0.38, 0.30, 0.14, 0.06]
    idade_genero = []
    for fx, pf in zip(faixas, pesos_f):
        for gen, pg in (('female', 0.88), ('male', 0.1), ('unknown', 0.02)):
            g = total['gasto'] * pf * pg
            idade_genero.append({'idade': fx, 'genero': gen, 'gasto': round(g, 2),
                                 'alcance': int(total['alcance'] * pf * pg),
                                 'leads': int(total['leads']['total'] * pf * pg * rnd.uniform(0.8, 1.2))})
    regioes = []
    for reg, p in (('Sao Paulo', 0.71), ('Rio de Janeiro', 0.09), ('Minas Gerais', 0.07),
                   ('Bahia', 0.06), ('Parana', 0.04), ('Outros', 0.03)):
        regioes.append({'regiao': reg, 'gasto': round(total['gasto'] * p, 2),
                        'alcance': int(total['alcance'] * p),
                        'leads': int(total['leads']['total'] * p * rnd.uniform(0.85, 1.1))})
    posic = []
    for plat, pos, p in (('instagram', 'reels', 0.34), ('instagram', 'feed', 0.27),
                         ('instagram', 'story', 0.21), ('facebook', 'feed', 0.12),
                         ('facebook', 'facebook_reels', 0.04), ('audience_network', 'classic', 0.02)):
        posic.append({'plataforma': plat, 'posicao': pos, 'gasto': round(total['gasto'] * p, 2),
                      'leads': int(total['leads']['total'] * p * rnd.uniform(0.7, 1.3))})

    return {'ok': True,
            'periodo': {'inicio': ini.isoformat(), 'fim': fim.isoformat(),
                        'inicio_anterior': ini_a.isoformat(), 'fim_anterior': fim_a.isoformat()},
            'total': total, 'anterior': ant, 'diario': diario, 'campanhas': campanhas,
            'anuncios': ads[:30],
            'publico': {'idade_genero': idade_genero, 'regioes': regioes, 'posicionamentos': posic}}


def _instagram_bloco(periodo, rnd):
    ini, fim, _, _ = meta.intervalo(periodo)
    dias = (fim - ini).days + 1
    posts = []
    n = max(2, int(dias / 2.5))
    for k in range(n):
        formato, legenda = POSTS[k % len(POSTS)]
        dia = fim - timedelta(days=int(k * dias / n))
        base = {'Reels': 4200, 'Carrossel': 1900, 'Imagem': 1100}[formato]
        alc = int(base * rnd.uniform(0.5, 1.8))
        posts.append({'data': dia.isoformat(), 'formato': formato, 'link': '#', 'miniatura': '',
                      'legenda': legenda, 'curtidas': int(alc * rnd.uniform(0.04, 0.08)),
                      'comentarios': int(alc * rnd.uniform(0.003, 0.01)), 'alcance': alc,
                      'salvos': int(alc * rnd.uniform(0.005, 0.03)),
                      'compartilhamentos': int(alc * rnd.uniform(0.002, 0.015)),
                      'interacoes': int(alc * 0.09),
                      'visualizacoes': int(alc * 1.6) if formato == 'Reels' else None})
    reach = int(sum(p['alcance'] for p in posts) * 1.9)
    m = {'reach': reach, 'accounts_engaged': int(reach * 0.07),
         'total_interactions': sum(p['interacoes'] for p in posts),
         'profile_views': int(reach * 0.045), 'website_clicks': int(reach * 0.006),
         'follows_and_unfollows': int(dias * 6.5)}
    return {'ok': True,
            'perfil': {'usuario': 'carlanunes.esteticanegra', 'nome': 'Carla Nunes Estetica Negra',
                       'seguidores': 12840, 'seguindo': 612, 'posts': 487, 'foto': ''},
            'metricas': m, 'anteriores': {k: int(v * rnd.uniform(0.78, 0.95)) for k, v in m.items()},
            'seguidores_dia': [{'data': (ini + timedelta(days=d)).isoformat(),
                                'novos': int(rnd.uniform(3, 12))} for d in range(min(dias, 30))],
            'posts': posts}


def gerar():
    rnd = random.Random(42)
    periodos = {}
    for p, rot in meta.PERIODOS.items():
        periodos[p] = {'rotulo': rot, 'anuncios': _anuncios_bloco(p, rnd),
                       'instagram': _instagram_bloco(p, rnd)}
    leads = []
    hoje = meta.date.today()
    for k in range(18):
        leads.append({'data': f"{(hoje - timedelta(days=k // 3)).isoformat()} "
                              f"{9 + (k * 5) % 10:02d}:{(k * 17) % 60:02d}",
                      'formulario': 'Avaliacao gratuita - Limpeza de pele',
                      'campanha': 'Limpeza de Pele Profunda - Formulario',
                      'anuncio': 'Reels - limpeza passo a passo' if k % 2 else 'Imagem - agenda aberta',
                      'campos': {'full_name': NOMES[k % len(NOMES)],
                                 'phone_number': f'+55 11 9{rnd.randint(1000, 9999)}-{rnd.randint(1000, 9999)}',
                                 'qual_procedimento_te_interessa?': PROCED[k % len(PROCED)]}})
    return {'demo': True,
            'pagina': {'ok': True, 'nome': 'Carla Nunes Estetica Negra', 'curtidas': 3110,
                       'seguidores': 3388, 'link': '#'},
            'leads_formulario': {'ok': True,
                                 'formularios': [{'nome': 'Avaliacao gratuita - Limpeza de pele',
                                                  'status': 'ACTIVE', 'total': 214}],
                                 'leads': leads},
            'periodos': periodos,
            'metas': {'cpl_alvo': 12.0, 'orcamento_mensal': 4500.0}}
