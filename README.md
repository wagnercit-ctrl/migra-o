# Carla Nunes Estética Negra - Integração Meta + Painel

Painel de marketing da clínica com os dados do Facebook e do Instagram num lugar só. É um arquivo
HTML que abre no navegador, inclusive no celular, e é atualizado com um clique ou todo dia,
automaticamente.

## O que o painel mostra

Tudo pode ser visto em 4 períodos: **últimos 7 dias, últimos 30 dias, mês atual e mês passado**.
Cada número vem comparado com o período anterior de mesmo tamanho.

| Bloco | Conteúdo |
|---|---|
| Resumo | investimento, leads, custo por lead (contra a meta), alcance, taxa de clique, seguidores |
| O que olhar agora | alertas automáticos: campanha gastando sem lead, custo por lead alto ou subindo, público saturado (frequência), anúncio com pouco clique, melhor anúncio, melhor formato no Instagram |
| Investimento e leads por dia | gráfico diário e o funil impressões > cliques > leads |
| Campanhas | status, orçamento, investido, leads, custo por lead, alcance, CTR e frequência (dá para ordenar) |
| Anúncios que mais trazem lead | criativos com miniatura, do menor custo por lead para o maior |
| Quem está virando lead | idade, gênero, estados e onde o anúncio aparece (Reels, Feed, Stories...) |
| Instagram | seguidores, alcance, contas engajadas, visitas ao perfil, cliques no link, novos seguidores por dia, alcance médio por formato e os posts do período (ordenáveis por alcance, salvos, compartilhamentos...) |
| Leads dos formulários | nome, WhatsApp (com link direto para abrir a conversa), procedimento de interesse e anúncio de origem |

**Lead** = conversa iniciada pelo anúncio (WhatsApp/Direct/Messenger) + formulário instantâneo +
lead marcado pelo pixel no site.

## Uso

| Arquivo | O que faz |
|---|---|
| `ver_demonstracao.bat` | abre o painel com números fictícios (para mostrar antes do acesso) |
| `atualizar_painel.bat` | puxa os dados reais da Meta e abre o painel |
| `agendar_atualizacao_diaria.bat` | agenda a atualização todo dia às 07:00 |

Linha de comando:

```
pip install -r requirements.txt
python painel/gerar_painel.py --testar    # o que o token enxerga
python painel/gerar_painel.py --abrir     # gera e abre
python painel/gerar_painel.py --resumo    # imprime o resumo da semana em texto (para WhatsApp)
```

O painel sai em `painel/saida/painel.html`, e os dados brutos em `painel/saida/dados.json`.

## Instalação

1. Python 3.10+ e `pip install -r requirements.txt`.
2. Liberar o acesso da Meta: **[docs/COMO_LIBERAR_ACESSO_META.md](docs/COMO_LIBERAR_ACESSO_META.md)**.
3. Copiar `config/.env.example` para `config/.env` e preencher.
4. `python painel/gerar_painel.py --testar` e depois `atualizar_painel.bat`.

## Estrutura

```
INTEGRACOES/meta_api.py     cliente da Meta (somente leitura): anúncios, Instagram, página, formulários
painel/gerar_painel.py      coleta, alertas, resumo em texto e montagem do HTML
painel/template.html        o painel (HTML único; gráficos via Chart.js)
painel/demo.py              dados fictícios do modo demonstração
config/.env.example         campos de configuração (todos lidos pelo código)
docs/                       passo a passo do acesso
```

## Segurança

- A integração **só lê**. Nenhuma função altera campanha, orçamento ou status.
- `config/.env` (token) e `painel/saida/` (com nomes e telefones dos leads) estão no
  `.gitignore`. Não mande o `painel.html` para fora da clínica: ele contém os leads.
