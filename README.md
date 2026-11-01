# ADVBOX para Infinitum

Motor de migracao de dados do ADVBOX para o Infinitum, via APIs oficiais. Retomavel, sem duplicar e com dry-run por padrao.
O ADVBOX e **somente lido** (apenas GET, 28/min para respeitar o limite de 30/min).

| ADVBOX | Infinitum |
|---|---|
| Clientes | database `Clientes` (ganha campos novos) |
| Processos | database `Processos` |
| Movimentacoes | database `Movimentacoes` |
| Lancamentos financeiros | database `Lancamentos` |
| Tarefas pendentes | tarefas da organizacao |

## Antes de comecar
1. `pip install -r requirements.txt`
2. Copie `.env.example` para `.env` e preencha os dois tokens.
3. **Crie na tela do Infinitum** os databases vazios `Clientes`, `Processos`, `Movimentacoes` e `Lancamentos`
   (o `POST /databases` esta documentado mas devolve 404 na API publica; os *campos* o motor cria sozinho).

## Uso
```
python migrar_advbox_infinitum.py extrair [--sem-movimentacoes]   # le o ADVBOX e salva snapshot local
python migrar_advbox_infinitum.py resumo
python migrar_advbox_infinitum.py migrar                           # dry-run: nao grava nada
python migrar_advbox_infinitum.py migrar --executar --limite 3     # teste pequeno, confira na tela
python migrar_advbox_infinitum.py migrar --executar                # tudo
python migrar_advbox_infinitum.py migrar --executar -e clientes,processos
python migrar_advbox_infinitum.py status
```

## Cuidados
- A API do Infinitum **nao tem DELETE de registro**: sempre comece com `--limite 3`.
- Cliente ja existente (mesmo CPF/CNPJ ou e-mail) e completado, nao duplicado.
- O Infinitum so tem os usuarios da sua organizacao: as tarefas vao para o dono e o responsavel original fica na descricao.
- Documentos/anexos nao migram (a API publica nao tem upload).
- `migracao_infinitum_snapshot.json` e `..._estado.json` contem dados de clientes: ja estao no `.gitignore`, nao publique.
