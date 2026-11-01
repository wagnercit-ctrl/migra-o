"""
Motor de migracao ADVBOX -> Infinitum ()

Fluxo em 3 etapas, todas retomaveis:
  1. extrair  : le o ADVBOX (SOMENTE GET) e grava um snapshot local em JSON
  2. preparar : garante os databases/campos no Infinitum (so com --executar)
  3. migrar   : grava no Infinitum (dry-run por padrao; so grava com --executar)

Mapeamento:
  ADVBOX customers     -> database "Clientes"   (ja existe; so ganha campos novos)
  ADVBOX lawsuits      -> database "Processos"
  ADVBOX movements     -> database "Movimentacoes"
  ADVBOX transactions  -> database "Lancamentos"
  ADVBOX posts (tarefas pendentes) -> tarefas da organizacao

Seguranca:
  - Nunca escreve no ADVBOX (so GET, 28/min para respeitar o limite de 30/min).
  - Idempotente: estado em migracao_infinitum_estado.json (advbox_id -> id Infinitum).
    Rodar de novo nao duplica; clientes tambem sao casados por CPF/CNPJ ja existente.
  - A API do Infinitum nao tem DELETE de registro: comece com --limite 3 e confira na tela.

Uso:
  python migrar_advbox_infinitum.py extrair [--sem-movimentacoes]
  python migrar_advbox_infinitum.py resumo
  python migrar_advbox_infinitum.py migrar                      # dry-run
  python migrar_advbox_infinitum.py migrar --executar --limite 3
  python migrar_advbox_infinitum.py migrar --executar -e clientes,processos
  python migrar_advbox_infinitum.py status
"""
import argparse
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

import requests
from dotenv import dotenv_values

PASTA = Path(__file__).resolve().parent
SNAPSHOT = PASTA / 'migracao_infinitum_snapshot.json'
ESTADO = PASTA / 'migracao_infinitum_estado.json'

ADVBOX_URL = 'https://app.advbox.com.br/api/v1'
INFINITUM_URL = 'https://public.infinitum.app.br/api/v1/public'
# Defina no .env: INFINITUM_ORG_ID e (opcional) INFINITUM_DB_CLIENTES.
# Se INFINITUM_DB_CLIENTES ficar vazio, o motor usa o database chamado "Clientes".

ENTIDADES = ['clientes', 'processos', 'movimentacoes', 'financeiro', 'tarefas']


# ============================================================
# CONFIG / HTTP
# ============================================================

def _env():
    """Le o .env ao lado do script; variaveis de ambiente tem prioridade."""
    cfg = {}
    p = PASTA / '.env'
    if p.exists():
        cfg.update({k: v for k, v in dotenv_values(p).items() if v})
    cfg.update({k: v for k, v in os.environ.items() if k.startswith(('ADVBOX_', 'INFINITUM_'))})
    return cfg


CFG = _env()
ORG_PAB = CFG.get('INFINITUM_ORG_ID', '')
DB_CLIENTES = CFG.get('INFINITUM_DB_CLIENTES', '')


def _tok(nome):
    v = CFG.get(nome)
    if not v:
        sys.exit(f'ERRO: {nome} nao encontrado (.env ao lado do script)')
    return v


class Limitador:
    """Garante no maximo N chamadas por minuto."""

    def __init__(self, por_minuto):
        self.intervalo = 60.0 / por_minuto
        self.ultimo = 0.0

    def esperar(self):
        falta = self.intervalo - (time.time() - self.ultimo)
        if falta > 0:
            time.sleep(falta)
        self.ultimo = time.time()


_lim_advbox = Limitador(28)
_lim_infinitum = Limitador(120)


def advbox_get(endpoint, params=None):
    """GET no ADVBOX (unico verbo usado aqui) com limite de taxa e retry."""
    h = {'Authorization': f'Bearer {_tok("ADVBOX_API_TOKEN")}',
         'User-Agent': 'advbox-para-infinitum/1.0', 'Accept': 'application/json'}
    for tentativa in range(5):
        _lim_advbox.esperar()
        r = requests.get(f'{ADVBOX_URL}{endpoint}', headers=h, params=params, timeout=90)
        if r.status_code == 429:
            time.sleep(int(r.headers.get('Retry-After', 30)))
            continue
        if r.status_code >= 500:
            time.sleep(5 * (tentativa + 1))
            continue
        r.raise_for_status()
        return r.json() if r.text else {}
    raise RuntimeError(f'ADVBOX {endpoint}: falhou apos retries')


def infinitum(metodo, endpoint, params=None, corpo=None):
    h = {'X-Public-Token': _tok('INFINITUM_PUBLIC_TOKEN'),
         'Content-Type': 'application/json', 'Accept': 'application/json'}
    for tentativa in range(5):
        _lim_infinitum.esperar()
        r = requests.request(metodo, f'{INFINITUM_URL}{endpoint}', headers=h,
                             params=params, json=corpo, timeout=60)
        if r.status_code == 429:
            time.sleep(int(r.headers.get('Retry-After', 15)))
            continue
        if r.status_code >= 500:
            time.sleep(4 * (tentativa + 1))
            continue
        if r.status_code >= 400:
            raise RuntimeError(f'Infinitum {metodo} {endpoint} -> {r.status_code}: {r.text[:300]}')
        return r.json() if r.text else {}
    raise RuntimeError(f'Infinitum {metodo} {endpoint}: falhou apos retries')


def _lista(resp, *chaves):
    if isinstance(resp, list):
        return resp
    for c in chaves + ('data', 'records', 'items'):
        if isinstance(resp, dict) and isinstance(resp.get(c), list):
            return resp[c]
    return []


# ============================================================
# ARQUIVOS (snapshot e estado)
# ============================================================

def _ler(p, padrao):
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else padrao


def _gravar(p, obj):
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding='utf-8')
    tmp.replace(p)


def estado():
    e = _ler(ESTADO, {})
    e.setdefault('databases', {})   # nome -> database_id
    e.setdefault('campos', {})      # nome_db -> [field_id,...]
    for ent in ENTIDADES:
        e.setdefault(ent, {})       # advbox_id -> id Infinitum
    e.setdefault('erros', [])
    return e


# ============================================================
# 1. EXTRAIR (ADVBOX, somente leitura)
# ============================================================

def _paginar(endpoint, limite, params=None):
    todos, offset = [], 0
    while True:
        p = dict(params or {}, limit=limite, offset=offset)
        d = advbox_get(endpoint, p)
        linhas = d.get('data', [])
        todos.extend(linhas)
        total = d.get('totalCount', 0)
        print(f'  {endpoint}: {len(todos)}/{total}')
        if not linhas or len(todos) >= total:
            return todos
        offset += limite


def cmd_extrair(args):
    snap = _ler(SNAPSHOT, {})
    if args.refazer:
        snap = {}
    if 'settings' not in snap:
        snap['settings'] = advbox_get('/settings')
    for chave, endpoint, lim in (('customers', '/customers', 1000),
                                 ('lawsuits', '/lawsuits', 1000),
                                 ('transactions', '/transactions', 1000),
                                 ('posts', '/posts', 100)):
        if chave not in snap:
            print(f'Extraindo {chave}...')
            snap[chave] = _paginar(endpoint, lim)
            _gravar(SNAPSHOT, snap)
    if not args.sem_movimentacoes:
        snap.setdefault('movements', {})
        pend = [str(p['id']) for p in snap['lawsuits'] if str(p['id']) not in snap['movements']]
        print(f'Movimentacoes: {len(pend)} processos a consultar (~{len(pend) * 2.2 / 60:.0f} min)')
        for i, lid in enumerate(pend, 1):
            try:
                d = advbox_get(f'/movements/{lid}')
                snap['movements'][lid] = d.get('data', []) if isinstance(d, dict) else []
            except requests.HTTPError as e:
                print(f'  ! processo {lid}: {e}')
                snap['movements'][lid] = []
            if i % 25 == 0:
                _gravar(SNAPSHOT, snap)
                print(f'  movimentacoes {i}/{len(pend)}')
    _gravar(SNAPSHOT, snap)
    print(f'\nSnapshot salvo em {SNAPSHOT}')
    cmd_resumo(args)


def cmd_resumo(_args=None):
    snap = _ler(SNAPSHOT, None)
    if not snap:
        sys.exit('Sem snapshot. Rode "extrair" primeiro.')
    print('\nSNAPSHOT ADVBOX')
    for k in ('customers', 'lawsuits', 'transactions', 'posts'):
        print(f'  {k:14s} {len(snap.get(k, []))}')
    mov = snap.get('movements')
    print(f'  {"movements":14s} {sum(len(v) for v in mov.values()) if mov else "(nao extraido)"}')


# ============================================================
# 2. SCHEMA NO INFINITUM
# ============================================================

# (field_id, label, tipo)
CAMPOS_CLIENTES = [
    ('advbox_id', 'ID ADVBOX', 'short_text'),
    ('celular', 'Celular', 'phone'),
    ('rg', 'RG', 'short_text'),
    ('sexo', 'Sexo', 'short_text'),
    ('estado_civil', 'Estado civil', 'short_text'),
    ('profissao', 'Profissao', 'short_text'),
    ('cep', 'CEP', 'short_text'),
    ('endereco', 'Endereco', 'short_text'),
    ('cidade', 'Cidade', 'short_text'),
    ('uf', 'UF', 'short_text'),
    ('data_nascimento', 'Data de nascimento', 'date'),
    ('ctps', 'CTPS', 'short_text'),
    ('pis', 'PIS', 'short_text'),
    ('origem_advbox', 'Origem (ADVBOX)', 'short_text'),
    ('cadastrado_advbox_em', 'Cadastrado no ADVBOX em', 'date'),
    ('processos_advbox', 'Processos (numeros)', 'long_text'),
]

DATABASES_NOVOS = {
    'Processos': {
        'descricao': 'Processos migrados do ADVBOX',
        'cor': '#7C3AED',
        'campos': [
            ('advbox_id', 'ID ADVBOX', 'short_text'),
            ('numero_processo', 'Numero do processo', 'short_text'),
            ('numero_protocolo', 'Protocolo', 'short_text'),
            ('pasta', 'Pasta', 'short_text'),
            ('cliente', 'Cliente(s)', 'long_text'),
            ('cliente_cpf', 'CPF/CNPJ do cliente', 'short_text'),
            ('tipo_acao', 'Tipo de acao', 'short_text'),
            ('grupo', 'Grupo/Area', 'short_text'),
            ('responsavel', 'Responsavel', 'short_text'),
            ('fase', 'Fase', 'short_text'),
            ('etapa', 'Etapa', 'short_text'),
            ('data_processo', 'Data do processo', 'date'),
            ('honorarios_previstos', 'Honorarios previstos', 'currency'),
            ('honorarios_recebidos', 'Honorarios recebidos', 'currency'),
            ('contingencia', 'Contingencia', 'short_text'),
            ('encerramento', 'Status de encerramento', 'short_text'),
            ('saida_producao', 'Saida producao', 'short_text'),
            ('saida_execucao', 'Saida execucao', 'short_text'),
            ('cadastrado_advbox_em', 'Cadastrado no ADVBOX em', 'date'),
            ('observacoes', 'Observacoes', 'long_text'),
        ],
    },
    'Movimentacoes': {
        'descricao': 'Andamentos dos processos migrados do ADVBOX',
        'cor': '#0891B2',
        'campos': [
            ('advbox_processo_id', 'ID processo ADVBOX', 'short_text'),
            ('numero_processo', 'Numero do processo', 'short_text'),
            ('cliente', 'Cliente(s)', 'long_text'),
            ('data', 'Data', 'date'),
            ('origem', 'Origem', 'short_text'),
            ('titulo', 'Titulo', 'short_text'),
            ('descricao', 'Descricao', 'long_text'),
        ],
    },
    'Lancamentos': {
        'descricao': 'Lancamentos financeiros migrados do ADVBOX',
        'cor': '#16A34A',
        'campos': [
            ('advbox_id', 'ID ADVBOX', 'short_text'),
            ('tipo', 'Tipo', 'short_text'),
            ('descricao', 'Descricao', 'long_text'),
            ('valor', 'Valor', 'currency'),
            ('vencimento', 'Vencimento', 'date'),
            ('pagamento', 'Pagamento', 'date'),
            ('competencia', 'Competencia', 'short_text'),
            ('categoria', 'Categoria', 'short_text'),
            ('centro_custo', 'Centro de custo', 'short_text'),
            ('banco_debito', 'Banco (debito)', 'short_text'),
            ('banco_credito', 'Banco (credito)', 'short_text'),
            ('responsavel', 'Responsavel', 'short_text'),
            ('cliente', 'Cliente', 'short_text'),
            ('cliente_cpf', 'CPF/CNPJ', 'short_text'),
            ('numero_processo', 'Numero do processo', 'short_text'),
            ('advbox_processo_id', 'ID processo ADVBOX', 'short_text'),
            ('interno', 'Interno', 'short_text'),
            ('recorrente', 'Recorrente', 'short_text'),
        ],
    },
}


def _campos_existentes(db_id):
    return {c['field_id'] for c in _lista(
        infinitum('GET', '/database-fields', {'database_id': db_id, 'limit': 500}), 'fields')}


def _garantir_campos(db_id, defs, executar):
    existentes = _campos_existentes(db_id)
    falta = [d for d in defs if d[0] not in existentes]
    pos = len(existentes)
    for fid, label, tipo in falta:
        print(f'    + campo {fid} ({tipo})')
        if executar:
            infinitum('POST', '/database-fields', corpo={
                'organization_id': ORG_PAB, 'database_id': db_id, 'field_id': fid, 'uuid': str(uuid.uuid4()),
                'label': label, 'type': tipo, 'required': False, 'position': pos})
        pos += 1
    return len(falta)


def cmd_preparar(args, est=None):
    est = est or estado()
    executar = args.executar
    print('Preparando schema no Infinitum' + ('' if executar else ' (dry-run)'))
    est['databases']['Clientes'] = DB_CLIENTES
    print('  Clientes (existente)')
    _garantir_campos(DB_CLIENTES, CAMPOS_CLIENTES, executar)

    existentes = {d['name']: d['id'] for d in _lista(
        infinitum('GET', '/databases', {'organization_id': ORG_PAB, 'limit': 100}))}
    for nome, cfg in DATABASES_NOVOS.items():
        db_id = existentes.get(nome) or est['databases'].get(nome)
        if db_id:
            print(f'  {nome} (existente)')
        else:
            print(f'  {nome} (criar)')
            if not executar:
                continue
            try:
                db_id = infinitum('POST', '/databases', corpo={
                    'name': nome, 'description': cfg['descricao'], 'color': cfg['cor'],
                    'sector': 'legal', 'organization_id': ORG_PAB})['id']
            except RuntimeError as e:
                # POST /databases nao esta roteado na API publica (404): criar na tela
                print(f'    ! nao foi possivel criar via API ({str(e)[:60]}).')
                print(f'      Crie o database "{nome}" (vazio) na tela do Infinitum e rode de novo.')
                continue
        est['databases'][nome] = db_id
        _garantir_campos(db_id, cfg['campos'], executar)
    if executar:
        _gravar(ESTADO, est)
    return est


# ============================================================
# 3. TRANSFORMACOES ADVBOX -> Infinitum
# ============================================================

def _s(v):
    return '' if v is None else str(v).strip()


def _data(v):
    """Aceita 'YYYY-MM-DD[ HH:MM:SS]' ou 'DD/MM/YYYY' e devolve YYYY-MM-DD."""
    v = _s(v)
    if not v:
        return ''
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', v)
    if m:
        return m.group(0)
    m = re.match(r'(\d{2})/(\d{2})/(\d{4})', v)
    return f'{m.group(3)}-{m.group(2)}-{m.group(1)}' if m else ''


def _valor(v):
    try:
        return f'{float(v):.2f}' if v not in (None, '') else ''
    except (TypeError, ValueError):
        return ''


def _limpo(d):
    """Remove vazios para nao sobrescrever com lixo."""
    return {k: v for k, v in d.items() if v not in ('', None)}


def _endereco(c):
    return ', '.join(x for x in (_s(c.get('street')),) if x)


def t_cliente(c, lawsuits_por_cliente):
    procs = lawsuits_por_cliente.get(c['id'], [])
    return _s(c.get('name')), _limpo({
        'nome': _s(c.get('name')),
        'email': _s(c.get('email')),
        'telefone': _s(c.get('phone')) or _s(c.get('cellphone')),
        'celular': _s(c.get('cellphone')),
        'documento': _s(c.get('identification')),
        'rg': _s(c.get('document')),
        'sexo': _s(c.get('gender')),
        'estado_civil': _s(c.get('civil_status')),
        'profissao': _s(c.get('occupation')),
        'cep': _s(c.get('postalcode')),
        'endereco': _endereco(c),
        'cidade': _s(c.get('city')),
        'uf': _s(c.get('state')),
        'data_nascimento': _data(c.get('birthdate')),
        'ctps': _s(c.get('number_ctps')),
        'pis': _s(c.get('number_pis')),
        'observacoes': _s(c.get('notes')),
        'origem_advbox': _s(c.get('origin')),
        'cadastrado_advbox_em': _data(c.get('created_at')),
        'processos_advbox': '\n'.join(procs),
        'advbox_id': str(c['id']),
    })


def t_processo(p):
    clientes = p.get('customers') or []
    nomes = ', '.join(_s(c.get('name')) for c in clientes)
    cpfs = ', '.join(_s(c.get('identification')) for c in clientes if c.get('identification'))
    ident = _s(p.get('process_number')) or _s(p.get('protocol_number')) or _s(p.get('type')) or f'Processo {p["id"]}'
    titulo = f'{ident} - {nomes}' if nomes else ident
    return titulo, _limpo({
        'advbox_id': str(p['id']),
        'numero_processo': _s(p.get('process_number')),
        'numero_protocolo': _s(p.get('protocol_number')),
        'pasta': _s(p.get('folder')),
        'cliente': nomes,
        'cliente_cpf': cpfs,
        'tipo_acao': _s(p.get('type')),
        'grupo': _s(p.get('group')),
        'responsavel': _s(p.get('responsible')),
        'fase': _s(p.get('stage')),
        'etapa': _s(p.get('step')),
        'data_processo': _data(p.get('process_date')),
        'honorarios_previstos': _valor(p.get('fees_expec')),
        'honorarios_recebidos': _valor(p.get('fees_money')),
        'contingencia': _s(p.get('contingency')),
        'encerramento': _s(p.get('status_closure')),
        'saida_producao': _s(p.get('exit_production')),
        'saida_execucao': _s(p.get('exit_execution')),
        'cadastrado_advbox_em': _data(p.get('created_at')),
        'observacoes': _s(p.get('notes')),
    })


def t_movimentacao(m, proc):
    clientes = ', '.join(_s(c.get('name')) for c in (proc.get('customers') or []))
    desc = _s(m.get('description')) or _s(m.get('text')) or _s(m.get('title'))
    titulo = _s(m.get('title')) or desc[:80] or 'Movimentacao'
    return f'{_data(m.get("date"))} {titulo}'[:200], _limpo({
        'advbox_processo_id': str(proc['id']),
        'numero_processo': _s(proc.get('process_number')),
        'cliente': clientes,
        'data': _data(m.get('date')),
        'origem': _s(m.get('origin')),
        'titulo': _s(m.get('title')),
        'descricao': desc,
    })


def t_lancamento(t):
    tipo = {'income': 'Receita', 'expense': 'Despesa'}.get(_s(t.get('entry_type')), _s(t.get('entry_type')))
    desc = _s(t.get('description'))
    return f'{tipo}: {desc}'[:200] or f'Lancamento {t["id"]}', _limpo({
        'advbox_id': str(t['id']),
        'tipo': tipo,
        'descricao': desc,
        'valor': _valor(t.get('amount')),
        'vencimento': _data(t.get('date_due')),
        'pagamento': _data(t.get('date_payment')),
        'competencia': _s(t.get('competence')),
        'categoria': _s(t.get('category')),
        'centro_custo': _s(t.get('cost_center')),
        'banco_debito': _s(t.get('debit_bank')),
        'banco_credito': _s(t.get('credit_bank')),
        'responsavel': _s(t.get('responsible')),
        'cliente': _s(t.get('name')),
        'cliente_cpf': _s(t.get('identification')),
        'numero_processo': _s(t.get('process_number')),
        'advbox_processo_id': _s(t.get('lawsuit_id')),
        'interno': 'sim' if t.get('is_internal') else '',
        'recorrente': 'sim' if t.get('is_recurrent') else '',
    })


def t_tarefa(p, users_id):
    resp = ', '.join(_s(u.get('name')) for u in (p.get('users') or []) if isinstance(u, dict))
    proc = p.get('lawsuit')
    proc = proc if isinstance(proc, str) else (_s(proc.get('process_number')) if isinstance(proc, dict) else '')
    partes = [_s(p.get('notes'))]
    if resp:
        partes.append(f'Responsavel(is) no ADVBOX: {resp}')
    if proc:
        partes.append(f'Processo: {proc}')
    partes.append(f'[ADVBOX #{p["id"]}]')
    corpo = {
        'title': _s(p.get('task')) or f'Tarefa {p["id"]}',
        'description': '\n'.join(x for x in partes if x),
        'priority': 'medium',
        'status': 'pendente',
        'assigned_to_ids': users_id,
    }
    prazo = _data(p.get('date_deadline')) or _data(p.get('date'))
    if prazo:
        corpo['due_date'] = prazo
    return corpo


# ============================================================
# 3. MIGRAR
# ============================================================

def _criar_registro(db_id, titulo, valores):
    r = infinitum('POST', '/database-records', corpo={
        'database_id': db_id, 'title': titulo, 'values': valores})
    return r.get('id') or (r.get('data') or {}).get('id')


def _atualizar_registro(rid, titulo, valores):
    infinitum('PUT', f'/database-records/{rid}', corpo={'title': titulo, 'values': valores})


def _indice_clientes_existentes():
    """documento (so digitos) -> record_id, para nao duplicar quem ja esta no Infinitum."""
    idx, pagina = {}, 1
    while True:
        r = infinitum('GET', '/database-records', {'database_id': DB_CLIENTES, 'page': pagina, 'limit': 100})
        regs = _lista(r, 'records')
        for rec in regs:
            doc = re.sub(r'\D', '', _s((rec.get('values') or {}).get('documento')))
            if doc:
                idx[doc] = rec['id']
        if len(regs) < 100:
            return idx
        pagina += 1


def _rodar(nome, itens, est, executar, limite, fn):
    """Loop generico: pula o ja migrado, respeita limite, registra erro sem parar."""
    feitos = est[nome]
    pend = [(k, v) for k, v in itens if k not in feitos]
    if limite:
        pend = pend[:limite]
    print(f'\n[{nome}] total {len(itens)} | ja migrados {len(feitos)} | a processar {len(pend)}'
          + ('' if executar else ' (dry-run)'))
    ok = err = 0
    for i, (chave, dados) in enumerate(pend, 1):
        if not executar:
            if i <= 2:
                print('  exemplo:', json.dumps(dados, ensure_ascii=False)[:400])
            continue
        try:
            novo = fn(dados)
            if novo:
                feitos[chave] = novo
                ok += 1
        except Exception as e:  # noqa: BLE001 - erro de um item nao pode parar o lote
            err += 1
            est['erros'].append({'entidade': nome, 'advbox_id': chave, 'erro': str(e)[:300]})
            print(f'  ! {nome} {chave}: {e}')
        if i % 25 == 0:
            _gravar(ESTADO, est)
            print(f'  {nome}: {i}/{len(pend)}')
    if executar:
        _gravar(ESTADO, est)
        print(f'  {nome}: {ok} criados, {err} erros')


def _tem_db(est, nome, args):
    if est['databases'].get(nome) or not args.executar:
        return True
    print(f'\n[{nome}] pulado: database "{nome}" nao existe no Infinitum (crie na tela, vazio)')
    return False


def cmd_migrar(args):
    snap = _ler(SNAPSHOT, None)
    if not snap:
        sys.exit('Sem snapshot. Rode "extrair" primeiro.')
    est = estado()
    if not args.executar:
        print('*** DRY-RUN: nada sera gravado. Use --executar para gravar. ***')
    escolhidas = [e.strip() for e in args.entidades.split(',')] if args.entidades else ENTIDADES
    invalidas = set(escolhidas) - set(ENTIDADES)
    if invalidas:
        sys.exit(f'Entidades invalidas: {invalidas}. Validas: {ENTIDADES}')

    precisa_schema = any(e in escolhidas for e in ('clientes', 'processos', 'movimentacoes', 'financeiro'))
    if precisa_schema:
        cmd_preparar(args, est)
        if not args.executar and not all(n in est['databases'] for n in DATABASES_NOVOS):
            print('  (databases novos ainda nao existem; o dry-run mostra so os exemplos)')

    lawsuits = snap['lawsuits']
    procs_por_cliente = {}
    for p in lawsuits:
        for c in p.get('customers') or []:
            rotulo = _s(p.get('process_number')) or f'{_s(p.get("type"))} (#{p["id"]})'
            procs_por_cliente.setdefault(c['customer_id'], []).append(rotulo)

    if 'clientes' in escolhidas:
        existentes = _indice_clientes_existentes() if args.executar else {}

        def mk_cliente(dados):
            doc = re.sub(r'\D', '', _s(dados[1].get('documento')))
            if doc and doc in existentes:   # ja existe no Infinitum: so completa os campos
                rid = existentes[doc]
                _atualizar_registro(rid, dados[0], dados[1])
                return rid
            try:
                rid = _criar_registro(DB_CLIENTES, dados[0], dados[1])
            except RuntimeError as e:
                m = re.search(r'existing_record_id.{1,6}?([0-9a-f-]{36})', str(e))
                if 'duplicate_record' not in str(e) or not m:
                    raise
                rid = m.group(1)   # mesmo e-mail/documento ja cadastrado: completa o existente
                _atualizar_registro(rid, dados[0], dados[1])
            if doc:
                existentes[doc] = rid
            return rid
        itens = [(str(c['id']), t_cliente(c, procs_por_cliente)) for c in snap['customers']]
        _rodar('clientes', itens, est, args.executar, args.limite, mk_cliente)

    if 'processos' in escolhidas and _tem_db(est, 'Processos', args):
        db = est['databases'].get('Processos')
        itens = [(str(p['id']), t_processo(p)) for p in lawsuits]
        _rodar('processos', itens, est, args.executar, args.limite,
               lambda d: _criar_registro(db, d[0], d[1]))

    if 'movimentacoes' in escolhidas and _tem_db(est, 'Movimentacoes', args):
        db = est['databases'].get('Movimentacoes')
        movs = snap.get('movements')
        if movs is None:
            print('\n[movimentacoes] pulado: snapshot sem movimentacoes (extraia sem --sem-movimentacoes)')
        else:
            por_id = {str(p['id']): p for p in lawsuits}
            itens = []
            for lid, lista in movs.items():
                for n, m in enumerate(lista):
                    chave = f'{lid}:{m.get("id") or n}'
                    itens.append((chave, t_movimentacao(m, por_id[lid])))
            _rodar('movimentacoes', itens, est, args.executar, args.limite,
                   lambda d: _criar_registro(db, d[0], d[1]))

    if 'financeiro' in escolhidas and _tem_db(est, 'Lancamentos', args):
        db = est['databases'].get('Lancamentos')
        itens = [(str(t['id']), t_lancamento(t)) for t in snap['transactions']]
        _rodar('financeiro', itens, est, args.executar, args.limite,
               lambda d: _criar_registro(db, d[0], d[1]))

    if 'tarefas' in escolhidas:
        users = _lista(infinitum('GET', '/organization-users', {'organization_id': ORG_PAB}))
        dono = [u['user_id'] for u in users if u.get('role') == 'owner'][:1]
        itens = [(str(p['id']), t_tarefa(p, dono)) for p in snap['posts']]

        def mk_tarefa(corpo):
            r = infinitum('POST', f'/organizations/{ORG_PAB}/tasks', corpo=corpo)
            return (r.get('data') or r).get('id')
        _rodar('tarefas', itens, est, args.executar, args.limite, mk_tarefa)

    print('\nFim.' + ('' if args.executar else ' (dry-run; nada foi gravado)'))


def cmd_status(_args):
    est = estado()
    print('MIGRACAO ADVBOX -> INFINITUM')
    for e in ENTIDADES:
        print(f'  {e:14s} {len(est[e])} migrados')
    print(f'  erros          {len(est["erros"])}')
    for er in est['erros'][-5:]:
        print('   ', er)


def _resolver_ids():
    global ORG_PAB, DB_CLIENTES
    if not ORG_PAB:
        orgs = _lista(infinitum('GET', '/organizations/my'))
        if len(orgs) != 1:
            sys.exit('Defina INFINITUM_ORG_ID no .env (token com 0 ou varias organizacoes).')
        ORG_PAB = orgs[0]['id']
    if not DB_CLIENTES:
        dbs = _lista(infinitum('GET', '/databases', {'organization_id': ORG_PAB, 'limit': 100}))
        achados = [d['id'] for d in dbs if d['name'].strip().lower() == 'clientes']
        if not achados:
            sys.exit('Crie na tela do Infinitum um database chamado "Clientes" ou defina INFINITUM_DB_CLIENTES.')
        DB_CLIENTES = achados[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('extrair', help='le o ADVBOX (somente GET) e grava o snapshot')
    p.add_argument('--sem-movimentacoes', action='store_true', help='pula o /movements por processo (lento)')
    p.add_argument('--refazer', action='store_true', help='ignora o snapshot existente')
    p.set_defaults(fn=cmd_extrair)

    sub.add_parser('resumo', help='conta o que tem no snapshot').set_defaults(fn=cmd_resumo)

    p = sub.add_parser('preparar', help='cria databases/campos no Infinitum')
    p.add_argument('--executar', action='store_true')
    p.set_defaults(fn=cmd_preparar)

    p = sub.add_parser('migrar', help='grava no Infinitum (dry-run sem --executar)')
    p.add_argument('--executar', action='store_true', help='grava de verdade')
    p.add_argument('--limite', type=int, default=0, help='maximo de itens por entidade (0 = todos)')
    p.add_argument('-e', '--entidades', help=f'lista separada por virgula de: {",".join(ENTIDADES)}')
    p.set_defaults(fn=cmd_migrar)

    sub.add_parser('status', help='progresso e erros').set_defaults(fn=cmd_status)

    args = ap.parse_args()
    if args.cmd in ('preparar', 'migrar'):
        _resolver_ids()
    args.fn(args)


if __name__ == '__main__':
    main()
