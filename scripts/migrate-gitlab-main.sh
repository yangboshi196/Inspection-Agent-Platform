#!/usr/bin/env bash
# 将本地有效代码以 main 为唯一分支推送到新 GitLab 仓库（覆盖远程初始 README）。
# 用法：bash scripts/migrate-gitlab-main.sh [--push]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

REMOTE="${GITLAB_REMOTE:-http://192.168.0.28/root/safetyproductionagent.git}"
DO_PUSH=false
if [[ "${1:-}" == "--push" ]]; then
  DO_PUSH=true
fi

echo ">>> remote: $REMOTE"
git remote set-url origin "$REMOTE"

# 以 cj 为有效代码基线，main 对齐后不再推送 cj
if ! git show-ref --verify --quiet refs/heads/cj; then
  echo "错误：本地不存在 cj 分支，无法对齐代码基线" >&2
  exit 1
fi

STASHED=false
if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git status -u --porcelain | grep '^??')" ]]; then
  echo ">>> 暂存当前工作区改动（迁移后恢复到 main）"
  git stash push -u -m "migrate-gitlab-main-wip" || true
  STASHED=true
fi

echo ">>> main 对齐 cj ($(git rev-parse --short cj))"
git checkout main
git reset --hard cj

if $STASHED; then
  echo ">>> 恢复工作区改动到 main"
  git stash pop || true
fi

echo ">>> 从索引移除不应入库的大文件/运行时目录（保留工作区）"
git rm -r --cached webui/node_modules 2>/dev/null || true
git rm -r --cached data/knowledge_chroma 2>/dev/null || true
git rm --cached core webui/core 2>/dev/null || true
git rm --cached vaio-analysis-service/x86_64/lib*.so 2>/dev/null || true
git rm --cached vaio-analysis-service/x86_64/vaio-analysis-core 2>/dev/null || true

# 纳入迁移相关源码改动（排除 .gitignore 已忽略项）
git add .gitignore scripts/migrate-gitlab-main.sh 2>/dev/null || true
git add .cursor/rules/ docs/ scripts/*.py scripts/*.sh 2>/dev/null || true
git add agent_base/ inspection_platform/ vaio-analysis-service/scripts/ vaio-analysis-service/x86_64/conf/ vaio-analysis-service/x86_64/label/ 2>/dev/null || true

if ! git diff --cached --quiet || ! git diff --quiet; then
  git add -u
  git commit -m "$(cat <<'EOF'
chore: GitLab 版本迁移，main 对齐有效代码并清理误入库文件

main 以 cj 为基线；移除 node_modules、Chroma 运行时、本地 .so/core 等。
EOF
)" || true
fi

echo ""
echo ">>> 本地 main 已就绪：$(git log --oneline -1)"
echo ">>> 远程 cj 分支无需推送；后续开发直接在 main 上进行。"
echo ""

if $DO_PUSH; then
  echo ">>> 强制推送 main 到 origin（覆盖 GitLab 初始化 README）..."
  git push -f -u origin main
  echo ">>> 推送完成。"
else
  cat <<'EOF'
下一步（在本机有 GitLab 认证的环境执行）：

  bash scripts/migrate-gitlab-main.sh --push

或手动：

  git push -f -u origin main

若使用 PAT：

  git push -f -u http://root:<TOKEN>@192.168.0.28/root/safetyproductionagent.git main
EOF
fi
