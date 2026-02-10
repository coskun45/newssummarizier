import requests,json
payload = {"articles":[{"title":"Test Create Unique","url":"https://example.com/news/test-unique-12345","published_at":"2026-02-10T15:03:00+00:00"}]}
try:
    r = requests.post("http://127.0.0.1:8000/api/feeds/1/add-articles", json=payload)
    print(r.status_code)
    print(r.text)
except Exception as e:
    print('REQUEST FAILED', e)
