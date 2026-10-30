# Asistan değerlendirmesi (eval)

Asistan'a `dataset.yaml`'daki analiz sorularını gerçekten sorar ve her soru için şunları ölçer:
doğru araçları çağırdı mı, araçlar doğru veriyi getirdi mi, nihai rapor doğru mu.

```bash
docker compose up -d db                                   # yerel PostgreSQL (+ pgvector, embedding'ler)
cd backend
python -m evals.assistant.run_eval --gold-only            # yalnızca beklenen (altın) cevapları yazdırır, ücretsiz
python -m evals.assistant.run_eval --ids cnt-01,sem-01    # birkaç soru
python -m evals.assistant.run_eval --category semantik --no-judge
python -m evals.assistant.run_eval                        # tüm set (~37 soru, gerçek OpenAI maliyeti)
python -m evals.assistant.run_eval --repeat 3 --concurrency 4   # her soru 3 kez: geçme oranı + kararsız sorular
```

Çıktı `results/run-<zaman>.md` (özet: kategori × boyut tablosu, sık hata etiketleri, başarısız soruların
izi) ve `results/run-<zaman>.json` (tam iz) dosyalarıdır. `results/` git'e girmez.

## Veri seti

Beklenen sonuçlar sabit yazılmaz: her `gold` sorgusu koşu anında aynı DB'deki `chat_*` view'larından
hesaplanır. Bu sayede DB büyüdükçe ya da "bugün" değiştikçe set bayatlamaz. `ranges` altındaki zaman
ifadeleri ajanın kullandığı `resolve_time_range` ile çözülür, SQL'de `{t_from}` / `{t_to}` olarak
kullanılır (naive UTC, uçlar dahil).

| Alan | Anlamı |
|---|---|
| `expect.clarification` | `required` / `forbidden` / `optional`. Hazır cevap yoksa koşucu ilk seçeneği seçer |
| `expect.time_range` | ajanın kullandığı dönem (understand veya zaman aracı) bu range ile gün bazında aynı olmalı |
| `expect.tools_required` / `tools_forbidden` / `tools_any_of` | araç seçimi |
| `gold[].match` | `scalar` (tek değer), `rowset` (satırlar), `top_ids` (haber id'leri), `id_recall` (vektör arama isabeti), `chart` (grafik değerleri), `must_cite` (raporda atıf) |
| `report_must_match` / `report_must_not_match` | rapor için regex'ler |
| `rubric` | LLM hakemin beklediği analiz |

Vektör arama sorularının ilgili haber id'leri yerel DB'deki haberlere göre elle seçildi. DB değişirse
`--gold-only` ile kontrol edilmeli.

## Puanlar

`tool_selection`, `time_range`, `tool_results` (altın değer ajanın SQL/arama/grafik sonuçlarında var mı),
`answer_facts` (sayılar ve `[#id]` atıfları raporda var mı, uydurma id var mı) ve `judge` (hakem puanı 0-5).
Model kararları koşudan koşuya değiştiği için tek koşu ±2 soru oynar; bir düzeltmenin etkisini görmek
için `--repeat 3` kullanın. Rapor her sorunun geçme oranını ve kararsız (bazı koşularda geçen) soruları
listeler.

Bir soru, bütün boyutları tam aldığında ve hakem puanı en az 3/5 olduğunda geçer. Puanlama
`scoring.py`'de, testleri `tests/test_eval_scoring.py`'de.
