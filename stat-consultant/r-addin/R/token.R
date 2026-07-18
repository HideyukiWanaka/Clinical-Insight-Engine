# Read the local shared secret the backend writes at startup (Step 6).
#
# Zero-config auth: no token is ever pasted by hand. The backend writes a fresh
# token to ~/.stat-consultant/rstudio_token on every start; we re-read it on
# every poll so a backend restart self-heals within one poll interval.

read_shared_secret <- function() {
  path <- path.expand(file.path("~", ".stat-consultant", "rstudio_token"))
  if (!file.exists(path)) {
    stop(
      "Stat Consultant: 共有シークレットファイルが見つかりません。\n",
      "バックエンドが起動していることを確認してください。\n",
      "確認したパス: ", path, "\n",
      "（Windowsでパスが食い違う場合、バックエンド起動時のログに出力される",
      "絶対パスと比較してください。）",
      call. = FALSE
    )
  }
  trimws(readLines(path, n = 1, warn = FALSE))
}
