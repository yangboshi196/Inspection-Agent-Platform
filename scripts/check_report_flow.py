"""验证报告生成与数据库读取。"""
from __future__ import annotations

import httpx

BASE = "http://127.0.0.1:8010"


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=120) as c:
        login = c.post("/api/auth/login", json={"account": "zhang.gong", "password": "demo1234"})
        login.raise_for_status()
        h = {"Authorization": f"Bearer {login.json()['token']}"}

        lst = c.get("/api/inspection-reports/?limit=10", headers=h)
        lst.raise_for_status()
        data = lst.json()
        print(f"API list reports: total={data['total']}, returned={len(data['items'])}")
        for item in data["items"][:5]:
            rid = item["report_id"]
            detail = c.get(f"/api/inspection-reports/{rid}", headers=h)
            ok = detail.status_code == 200 and bool(detail.json().get("full_text") or detail.json().get("summary"))
            print(f"  {rid} status={item['status']} source={item.get('source')} detail_ok={ok}")

        plans = c.get("/api/report-plans/?limit=10", headers=h).json()["items"]
        plan = next((p for p in plans if p.get("enabled")), None)
        if not plan:
            print("no enabled plan, skip generate test")
            return
        before = data["total"]
        gen = c.post(f"/api/report-plans/{plan['plan_id']}/generate", headers=h)
        print(f"generate from plan {plan['plan_id']}: {gen.status_code}")
        if gen.status_code == 201:
            rep = gen.json()
            print(f"  created {rep['report_id']} title={rep['title'][:40]} status={rep['status']}")
        else:
            print(f"  error: {gen.text[:200]}")

        after = c.get("/api/inspection-reports/?limit=1", headers=h).json()["total"]
        print(f"report count before={before} after={after}")


if __name__ == "__main__":
    main()
