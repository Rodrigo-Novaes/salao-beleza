// ─── SISTEMA DE TEMAS ─────────────────────────────────────────────────────────
const TEMAS_CORES = {
  rose:        {dark:'#2a1f1a',rose:'#c9a99a',cream:'#f5f0ea',gold:'#c8a96e',warm:'#f0e8d8',mid:'#6b4c3b',lt:'#a08070',dr:'#8b3a3a'},
  sage:        {dark:'#1a2a1f',rose:'#8fb8a8',cream:'#eaf2ee',gold:'#7ab87a',warm:'#e4f0e8',mid:'#2d6a4a',lt:'#6a9a7a',dr:'#2d6a2d'},
  ocean:       {dark:'#1a2030',rose:'#7ab3c8',cream:'#eaf3f7',gold:'#4a90b8',warm:'#e0eff8',mid:'#1a5a80',lt:'#5a90aa',dr:'#1a4a6a'},
  plum:        {dark:'#1f1a2a',rose:'#b09ac9',cream:'#f0eaf8',gold:'#9b7ec8',warm:'#ede8f5',mid:'#5a3a8a',lt:'#8a6aaa',dr:'#4a2a7a'},
  gold:        {dark:'#1a1510',rose:'#d4a843',cream:'#faf6ee',gold:'#c8a96e',warm:'#f5edda',mid:'#7a5a20',lt:'#aa8a50',dr:'#8a5a10'},
  charcoal:    {dark:'#1a1a1a',rose:'#888888',cream:'#f2f2f2',gold:'#555555',warm:'#e8e8e8',mid:'#333333',lt:'#777777',dr:'#222222'},
  rose_sb:     {dark:'#2a1f1a',rose:'#c9a99a',cream:'#f5f0ea',gold:'#c8a96e',warm:'#f0e8d8',mid:'#6b4c3b',lt:'#a08070',dr:'#8b3a3a'},
  sage_sb:     {dark:'#1a2a1f',rose:'#8fb8a8',cream:'#eaf2ee',gold:'#7ab87a',warm:'#e4f0e8',mid:'#2d6a4a',lt:'#6a9a7a',dr:'#2d6a2d'},
  ocean_sb:    {dark:'#1a2030',rose:'#7ab3c8',cream:'#eaf3f7',gold:'#4a90b8',warm:'#e0eff8',mid:'#1a5a80',lt:'#5a90aa',dr:'#1a4a6a'},
  plum_sb:     {dark:'#1f1a2a',rose:'#b09ac9',cream:'#f0eaf8',gold:'#9b7ec8',warm:'#ede8f5',mid:'#5a3a8a',lt:'#8a6aaa',dr:'#4a2a7a'},
  light:       {dark:'#2a1f1a',rose:'#c9a99a',cream:'#f5f0ea',gold:'#c8a96e',warm:'#f0e8d8',mid:'#6b4c3b',lt:'#a08070',dr:'#8b3a3a'},
  light_sage:  {dark:'#1a2a1f',rose:'#8fb8a8',cream:'#eaf2ee',gold:'#7ab87a',warm:'#e4f0e8',mid:'#2d6a4a',lt:'#6a9a7a',dr:'#2d6a2d'},
  light_ocean: {dark:'#1a2030',rose:'#7ab3c8',cream:'#eaf3f7',gold:'#4a90b8',warm:'#e0eff8',mid:'#1a5a80',lt:'#5a90aa',dr:'#1a4a6a'},
  white_rose:  {dark:'#2a1f1a',rose:'#c9a99a',cream:'#f5f0ea',gold:'#c8a96e',warm:'#f0e8d8',mid:'#6b4c3b',lt:'#a08070',dr:'#8b3a3a'},
  white_sage:  {dark:'#1a2a1f',rose:'#8fb8a8',cream:'#eaf2ee',gold:'#7ab87a',warm:'#e4f0e8',mid:'#2d6a4a',lt:'#6a9a7a',dr:'#2d6a2d'},
  white_ocean: {dark:'#1a2030',rose:'#7ab3c8',cream:'#eaf3f7',gold:'#4a90b8',warm:'#e0eff8',mid:'#1a5a80',lt:'#5a90aa',dr:'#1a4a6a'},
  white_plum:  {dark:'#1f1a2a',rose:'#b09ac9',cream:'#f0eaf8',gold:'#9b7ec8',warm:'#ede8f5',mid:'#5a3a8a',lt:'#8a6aaa',dr:'#4a2a7a'},
  white_sb:    {dark:'#2a1f1a',rose:'#c9a99a',cream:'#f5f0ea',gold:'#c8a96e',warm:'#f0e8d8',mid:'#6b4c3b',lt:'#a08070',dr:'#8b3a3a'},
};

function _aplicarCores(t){
  const r = document.documentElement;
  r.style.setProperty('--dark',  t.dark);
  r.style.setProperty('--rose',  t.rose);
  r.style.setProperty('--cream', t.cream);
  r.style.setProperty('--gold',  t.gold);
  r.style.setProperty('--warm',  t.warm);
  r.style.setProperty('--mid',   t.mid);
  r.style.setProperty('--lt',    t.lt);
  r.style.setProperty('--dr',    t.dr);
}

// Carregar tema do servidor e aplicar
fetch('/api/config')
  .then(r => r.json())
  .then(cfg => {
    const nome = cfg.tema || 'rose';
    const t = TEMAS_CORES[nome];
    if(t) _aplicarCores(t);
  })
  .catch(() => {});