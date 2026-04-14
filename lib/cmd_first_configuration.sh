#!/usr/bin/env bash
# shellcheck shell=bash
cmd_first_configuration() {
  echo "=== Tedde first-configuration ==="
  echo "Repo: $REPO_ROOT"

  if [[ ! -f "$ENV_FILE" ]]; then
    if [[ -f "$REPO_ROOT/.env_example" ]]; then
      echo "Creez .env din .env_example — editează IP-urile și parolele înainte de a relua."
      cp "$REPO_ROOT/.env_example" "$ENV_FILE"
    fi
  fi
  require_env_file
  # Re-citește portul după ce .env poate fi tocmai creat
  export PY_SERVER_PORT="$(read_py_server_port)"
  export BASE_URL="http://127.0.0.1:${PY_SERVER_PORT}"

  echo ""
  echo "--- Pas 1: health standalone (ffmpeg, directoare, TCP camere) ---"
  if ! run_py_tool -m tools.health_standalone; then
    echo "Health critic a eșuat (overall=error). Remediază ffmpeg/directoare, apoi reîncearcă." >&2
    return 1
  fi

  local port
  port="$(read_py_server_port)"
  export PY_SERVER_PORT="$port"
  export BASE_URL="http://127.0.0.1:${port}"

  if ! port_listening "$port"; then
    echo ""
    read -r -p "Serverul nu rulează pe :$port. Pornești acum în background? [Y/n] " ans
    if [[ "${ans:-Y}" =~ ^[Nn] ]]; then
      echo "Continuăm fără server (doar snapshot + benchmark CLI; pre-testele HTTP vor fi sărite)."
    else
      # shellcheck source=lib/cmd_start.sh
      source "$LIB_DIR/cmd_start.sh"
      cmd_start background
      echo "Aștept /health (max ~45s) …"
      if ! wait_for_health 45; then
        echo "Serverul nu răspunde la timp. Verifică logs/uvicorn.log" >&2
        return 1
      fi
      echo "Server activ: $BASE_URL"
    fi
  else
    echo "Server deja activ pe $BASE_URL"
  fi

  local cam="1"
  if [[ -f "$ENV_FILE" ]]; then
    local line
    line="$(grep -E '^[[:space:]]*ALPR_CAMERA=' "$ENV_FILE" | tail -1 || true)"
    if [[ -n "$line" ]]; then
      cam="${line#*=}"
      cam="$(echo "$cam" | tr -d ' \r\"')"
    fi
  fi
  [[ -z "$cam" ]] && cam="1"

  echo ""
  echo "--- Pas 2: snapshot + benchmark ALPR + scriere .env (cameră $cam, main) ---"
  if ! run_py_tool -m tools.first_config_alpr --camera "$cam" --quality main; then
    local ec=$?
    if [[ "$ec" -eq 2 ]]; then
      echo "Nu s-a selectat niciun model (ieșire utilizator sau fără candidat)." >&2
    fi
    return "$ec"
  fi

  if port_listening "$port"; then
    echo ""
    echo "--- Pas 3: pre-teste HTTP ---"
    echo "GET /api/health (max 15s) …"
    curl -sS --max-time 15 "$BASE_URL/api/health" | head -c 2000 || echo "(api/health eșuat)"
    echo ""
    echo "POST /api/alpr/test (max 120s, poate descărca modele) …"
    curl -sS --max-time 120 -X POST "$BASE_URL/api/alpr/test" \
      -H "Content-Type: application/json" \
      -d "{\"camera\": $cam, \"quality\": \"main\"}" | head -c 2500 || echo "(alpr test eșuat)"
    echo ""
  else
    echo "Server oprit — sărite pre-testele HTTP. Pornește manual: ./lib/orchestrate.sh start"
  fi

  echo ""
  echo "=== First-configuration încheiat ==="
  echo "Dacă ai schimbat ALPR_DETECTOR_MODEL, repornește serverul: ./lib/orchestrate.sh stop && ./lib/orchestrate.sh start"
}
