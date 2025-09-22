export function leakCheck(promptTail: string, utter: string) {
  const badPhrases = [
    '［演出ノート］', '［内蔵ヒント］', '演出ノート', '内蔵ヒント',
    'canon:', 'lore:', 'pattern:', '台詞に出さない'
  ];
  const found: string[] = [];
  for (const p of badPhrases) if ((utter || '').includes(p)) found.push(p);
  const beats = ['BANter','PIVOT','PAYOFF'];
  for (const b of beats) if ((utter || '').includes(b)) found.push(b);
  return { ok: found.length === 0, found };
}

