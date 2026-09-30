// Baixa do DivulgaCandContas (TSE) os candidatos de SP e de presidente das Eleições 2026
// e grava em data/candidatos.json, que o app lê do próprio site (sem depender de CORS).
// Roda no GitHub Actions (.github/workflows/atualizar-candidatos.yml).
import { writeFile, mkdir } from 'node:fs/promises';

const TSE = 'https://divulgacandcontas.tse.jus.br/divulga/rest';
const API = TSE + '/v1';
const ANO = 2026;
const CARGOS = [
  { cod: 1, ue: 'BR', nome: 'Presidente' },
  { cod: 3, ue: 'SP', nome: 'Governador' },
  { cod: 5, ue: 'SP', nome: 'Senador' },
  { cod: 6, ue: 'SP', nome: 'Deputado Federal' },
  { cod: 7, ue: 'SP', nome: 'Deputado Estadual' },
];
const HEADERS = {
  'Accept': 'application/json, text/plain, */*',
  'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36',
  'Referer': 'https://divulgacandcontas.tse.jus.br/divulga/',
};

async function getJSON(url, tentativas = 4) {
  for (let i = 1; i <= tentativas; i++) {
    try {
      const r = await fetch(url, { headers: HEADERS, signal: AbortSignal.timeout(60000) });
      const txt = await r.text();
      if (!r.ok) throw new Error(`HTTP ${r.status}: ${txt.slice(0, 200)}`);
      return JSON.parse(txt);
    } catch (e) {
      console.log(`  tentativa ${i} falhou em ${url}: ${e.message}`);
      if (i === tentativas) throw e;
      await new Promise(r => setTimeout(r, 3000 * i));
    }
  }
}

const norm = s => String(s ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

async function descobrirEleicao() {
  if (process.env.ELEICAO_ID) return { id: process.env.ELEICAO_ID, nome: 'Eleições Gerais 2026' };
  const lista = await getJSON(`${API}/eleicao/ordinarias`);
  const arr = (Array.isArray(lista) ? lista : (lista.eleicoes || [])).filter(e => Number(e.ano) === ANO);
  console.log('Eleições de 2026 encontradas:', JSON.stringify(arr.map(e => ({ id: e.id, nome: e.nomeEleicao || e.descricaoEleicao, abr: e.tipoAbrangencia, turno: e.turno }))));
  if (!arr.length) throw new Error('Nenhuma eleição de 2026 em /eleicao/ordinarias');
  const score = e => {
    const n = norm(e.nomeEleicao || e.descricaoEleicao);
    return (String(e.tipoAbrangencia).toUpperCase() === 'F' ? 4 : 0) + (/geral|federal/.test(n) ? 3 : 0) + (String(e.turno) === '1' ? 2 : 0);
  };
  arr.sort((a, b) => score(b) - score(a));
  return { id: String(arr[0].id), nome: arr[0].nomeEleicao || arr[0].descricaoEleicao || 'Eleições Gerais 2026' };
}

function limpa(c) {
  const p = c.partido || {};
  const v = (c.vices && c.vices[0]) || null;
  return {
    id: c.id,
    n: String(c.numero ?? c.numeroCandidato ?? ''),
    nome: c.nomeUrna || c.nomeCandidatoUrna || c.nomeCompleto || '',
    completo: c.nomeCompleto || '',
    sigla: p.sigla || c.siglaPartido || '',
    pnum: String(p.numero ?? '').padStart(2, '0'),
    sit: c.descricaoSituacao || c.descricaoSituacaoCandidato || c.descricaoSituacaoCandidatura || '',
    vice: v ? (v.nm_URNA || v.nomeUrna || v.nomeUrnaVice || '') : '',
  };
}

const eleicao = await descobrirEleicao();
console.log('Eleição escolhida:', eleicao);
const cargos = {};
for (const cargo of CARGOS) {
  const data = await getJSON(`${API}/candidatura/listar/${ANO}/${cargo.ue}/${eleicao.id}/${cargo.cod}/candidatos`);
  const brutos = data.candidatos || [];
  if (brutos[0]) console.log(`Exemplo bruto (${cargo.nome}):`, JSON.stringify(brutos[0]).slice(0, 600));
  cargos[cargo.cod] = brutos.map(limpa).filter(c => c.n).sort((a, b) => a.n.localeCompare(b.n));
  console.log(`${cargo.nome}: ${cargos[cargo.cod].length} candidatos`);
}
if (!cargos[1].length || !cargos[3].length) throw new Error('Lista de presidente/governador vazia — não gravando.');

// Confere se a foto do TSE abre (o app mostra a foto direto do site do TSE)
const ex = cargos[3][0];
try {
  const r = await fetch(`${TSE}/arquivo/img/${eleicao.id}/${ex.id}/SP`, { headers: HEADERS });
  console.log('Teste de foto:', r.status, r.headers.get('content-type'), 'CORS:', r.headers.get('access-control-allow-origin'));
} catch (e) { console.log('Teste de foto falhou:', e.message); }

await mkdir('data', { recursive: true });
await writeFile('data/candidatos.json', JSON.stringify({ eleicao: { ...eleicao, ano: ANO }, atualizado: new Date().toISOString(), cargos }));
console.log('Gravado data/candidatos.json');
