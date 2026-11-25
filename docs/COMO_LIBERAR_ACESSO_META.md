# Como liberar o acesso da Meta para o painel

Leva uns 15 minutos e é feito uma vez só. Quem faz é alguém que seja **administrador do
Gerenciador de Negócios (Business) da clínica**. O token gerado no fim **não expira**.

O token fica no computador da clínica (`config/.env`) e é dela. Ele só **lê** os dados: o painel
não pausa, ativa nem altera nenhuma campanha.

## 1. Conferir se está tudo dentro do Business da clínica

Abra <https://business.facebook.com/settings>, escolha o portfólio da clínica e confira em
**Contas**:

- **Contas de anúncios**: a conta usada nos anúncios da clínica.
- **Páginas**: a página do Facebook da Carla Nunes Estética Negra.
- **Contas do Instagram**: o @ da clínica. Ele precisa ser **conta profissional** e estar
  **vinculado à página**.

Se algum desses itens não aparecer, use **Adicionar** para incluí-lo.

## 2. Criar o app (só para gerar o token)

1. Acesse <https://developers.facebook.com/apps> e clique em **Criar app**.
2. Escolha o tipo **Empresa (Business)**, dê o nome `Painel Carla Nunes` e vincule ao portfólio
   da clínica.
3. Não precisa publicar o app nem configurar mais nada.

## 3. Criar o usuário do sistema

1. Em **Configurações do negócio > Usuários > Usuários do sistema**, clique em **Adicionar**.
2. Nome: `painel`. Função: **Administrador**.
3. Clique em **Atribuir ativos** e dê acesso a:
   - **Conta de anúncios**: *Ver desempenho* (basta isso).
   - **Página**: acesso a *conteúdo*, *insights* e *leads*.
   - **Conta do Instagram**: acesso total ou *insights*.
   - **App** `Painel Carla Nunes`: *Gerenciar app*.

## 4. Gerar o token

1. Ainda em **Usuários do sistema > painel**, clique em **Gerar novo token**.
2. App: `Painel Carla Nunes`. Validade do token: **Nunca**.
3. Marque estas permissões:
   - `ads_read`
   - `read_insights`
   - `business_management`
   - `pages_show_list`
   - `pages_read_engagement`
   - `pages_manage_ads`
   - `leads_retrieval`
   - `instagram_basic`
   - `instagram_manage_insights`
4. Copie o token. **Ele aparece uma vez só.**

## 5. Liberar os leads dos formulários (só se a clínica usar formulário instantâneo)

Em **Configurações do negócio > Integrações > Acesso a leads**, escolha a página e confira se o
usuário do sistema `painel` e o app estão com acesso. Se essa tela já estiver liberada para
todos, não há nada a fazer.

## 6. Preencher o `config/.env`

Copie `config/.env.example` para `config/.env` e preencha:

| Campo | Onde achar |
|---|---|
| `META_ACCESS_TOKEN` | token do passo 4 |
| `META_AD_ACCOUNT` | Gerenciador de Anúncios, número da conta no topo, com `act_` na frente |
| `META_PAGE_ID` | Configurações do negócio > Páginas > clique na página (ID aparece no painel lateral) |
| `META_IG_USER_ID` | pode deixar vazio: o painel descobre pela página |
| `META_CPL_ALVO` | custo por lead que a clínica considera bom (ex.: 12) |
| `META_ORCAMENTO_MENSAL` | quanto pretende investir por mês (ex.: 4500) |

## 7. Testar

```
python painel/gerar_painel.py --testar
```

A conta de anúncios e a página da clínica precisam aparecer na lista. Depois disso, rode
`atualizar_painel.bat`.

## Se der erro

- **"(#200) Requires ads_read permission"** ou parecido: falta permissão no token (passo 4).
  Gere outro token marcando a permissão que falta.
- **Instagram sem acesso**: a conta não é profissional ou não está vinculada à página. Vincule
  pelo app do Instagram em *Configurações > Central de contas*.
- **Formulários sem acesso**: veja o passo 5.
- O painel continua funcionando com o que estiver liberado. A parte sem acesso mostra o motivo
  no próprio quadro.
