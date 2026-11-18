from backend.app import db

from .conftest import make_user


def test_register_login_me(client):
    r = client.post("/api/auth/register", json={"email": "Asha@Example.com", "password": "password123",
                                                "full_name": "Asha"})
    assert r.status_code == 201
    assert r.json()["user"]["email"] == "asha@example.com"
    assert r.json()["user"]["onboarded"] is False
    again = client.post("/api/auth/register", json={"email": "asha@example.com", "password": "password123",
                                                    "full_name": "Asha"})
    assert again.status_code == 409
    assert client.post("/api/auth/login", json={"email": "asha@example.com", "password": "wrong-pass"}).status_code == 401
    tok = client.post("/api/auth/login", json={"email": "asha@example.com", "password": "password123"}).json()["token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert me.status_code == 200 and me.json()["full_name"] == "Asha"


def test_protected_routes_need_a_valid_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    assert client.get("/api/profile").status_code == 401


def test_password_is_hashed_and_validated(client):
    short = client.post("/api/auth/register", json={"email": "s@example.com", "password": "short", "full_name": "S"})
    assert short.status_code == 422
    u = make_user(client)
    row = db.one("SELECT password_hash FROM users WHERE id = %s", (u["id"],))
    assert row["password_hash"] != "password123" and row["password_hash"].startswith("$2")


def test_onboarding_estimates_targets_and_saves_rules(client):
    u = make_user(client)
    opts = client.get("/api/profile/options").json()
    assert "peanut" in opts["allergens"] and "vegetarian" in opts["diets"]
    est = client.post("/api/profile/estimate", json={"sex": "male", "age": 25, "height_cm": 175, "weight_kg": 70,
                                                     "activity": "moderate", "goal": "maintain"}).json()
    # Mifflin-St Jeor: 10*70 + 6.25*175 - 5*25 + 5 = 1673.75, times 1.55 for moderate activity
    assert est["bmr"] == 1674 and abs(est["tdee"] - 1673.75 * 1.55) < 1
    body = {"sex": "female", "age": 30, "height_cm": 165, "weight_kg": 60, "activity": "light", "goal": "lose",
            "diet": "vegetarian", "allergies": ["Peanut", "peanut"], "restrictions": [" Mushroom "],
            "cuisines": ["Indian", "Atlantis"]}
    r = client.post("/api/profile/onboarding", json=body, headers=u["headers"])
    assert r.status_code == 200
    p = r.json()["profile"]
    assert p["calorie_target"] is not None and p["protein_target_g"] is not None
    assert p["allergies"] == ["peanut"] and p["restrictions"] == ["mushroom"] and p["cuisines"] == ["Indian"]
    assert client.get("/api/auth/me", headers=u["headers"]).json()["onboarded"] is True
    hist = client.get("/api/history/preferences", headers=u["headers"]).json()
    assert len(hist) == 1 and hist[0]["snapshot"]["diet"] == "vegetarian"


def test_onboarding_rejects_out_of_range_values(client):
    u = make_user(client)
    r = client.post("/api/profile/onboarding", json={"age": 7}, headers=u["headers"])
    assert r.status_code == 422
    r = client.put("/api/profile", json={"calorie_target": 99999}, headers=u["headers"])
    assert r.status_code == 422
