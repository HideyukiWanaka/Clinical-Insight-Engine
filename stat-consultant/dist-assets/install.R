# Stat Consultant インストーラ
#
# 使い方: RStudio のコンソールで、このファイルがある場所を指定して実行します。
#
#   source("<展開したフォルダ>/install.R")
#
# 実行内容は 4 つだけです:
#   1. 必要な R パッケージを導入
#   2. Addin パッケージ (statConsultantAddin) を導入
#   3. バックエンドの場所を ~/.stat-consultant/config.json に記録
#   4. (macOS のみ) ダウンロード検疫属性を解除
#
# 管理者権限は不要で、書き込むのは利用者自身のホーム配下だけです。

local({

  # このスクリプト自身の場所 = 展開したフォルダ。source() 経由なら sys.frame
  # から取れますが、取れない場合は作業ディレクトリにフォールバックします。
  script_dir <- tryCatch(
    dirname(normalizePath(sys.frame(1)$ofile)),
    error = function(e) normalizePath(getwd())
  )

  say <- function(...) message("[Stat Consultant] ", ...)

  say("インストール元: ", script_dir)

  ## 1. 依存パッケージ ------------------------------------------------------
  needed <- c("rstudioapi", "httr2", "later", "processx", "jsonlite")
  missing <- needed[!vapply(needed, requireNamespace, logical(1), quietly = TRUE)]
  if (length(missing)) {
    say("不足パッケージを導入します: ", paste(missing, collapse = ", "))
    install.packages(missing, repos = "https://cloud.r-project.org")
  } else {
    say("依存パッケージは導入済みです。")
  }

  ## 2. Addin パッケージ ----------------------------------------------------
  tarball <- list.files(script_dir, pattern = "^statConsultantAddin_.*\\.tar\\.gz$",
                        full.names = TRUE)
  if (length(tarball) == 0) {
    stop("statConsultantAddin_*.tar.gz が ", script_dir,
         " に見つかりません。zip を丸ごと展開したか確認してください。",
         call. = FALSE)
  }
  say("Addin を導入します: ", basename(tarball[1]))
  install.packages(tarball[1], repos = NULL, type = "source")

  ## 3. バックエンドの場所を記録 --------------------------------------------
  exe_name <- if (.Platform$OS.type == "windows") {
    "stat-consultant-backend.exe"
  } else {
    "stat-consultant-backend"
  }
  backend <- file.path(script_dir, "stat-consultant-backend", exe_name)
  if (!file.exists(backend)) {
    stop("バックエンド実行ファイルが見つかりません: ", backend, call. = FALSE)
  }

  state_dir <- path.expand(file.path("~", ".stat-consultant"))
  if (!dir.exists(state_dir)) dir.create(state_dir, recursive = TRUE, mode = "0700")
  cfg_path <- file.path(state_dir, "config.json")

  # 既存の設定は保持し、backend_path だけ差し替える（将来キーが増えても壊さない）
  cfg <- if (file.exists(cfg_path)) {
    tryCatch(jsonlite::fromJSON(cfg_path), error = function(e) list())
  } else {
    list()
  }
  cfg$backend_path <- normalizePath(backend)
  writeLines(jsonlite::toJSON(cfg, auto_unbox = TRUE, pretty = TRUE), cfg_path)
  say("バックエンドの場所を記録しました: ", cfg_path)

  ## 4. macOS: 検疫属性の解除 ------------------------------------------------
  # ブラウザや AirDrop で受け取ったファイルには com.apple.quarantine が付き、
  # 未署名バイナリは Gatekeeper に阻まれます。onedir 構成では中の実行ファイル
  # 1つ1つで警告が出るため、ツリー全体をまとめて解除します。
  if (Sys.info()[["sysname"]] == "Darwin") {
    target <- file.path(script_dir, "stat-consultant-backend")
    res <- suppressWarnings(system2("xattr",
      c("-dr", "com.apple.quarantine", shQuote(target)),
      stdout = TRUE, stderr = TRUE))
    status <- attr(res, "status")
    if (is.null(status) || status == 0) {
      say("検疫属性を解除しました（Gatekeeper 対策）。")
    } else {
      say("検疫属性の解除に失敗しました。初回起動時に警告が出る場合は、",
          "ターミナルで次を実行してください:\n",
          "  xattr -dr com.apple.quarantine ", target)
    }
  }

  ## 完了 --------------------------------------------------------------------
  say("インストール完了。")
  message(
    "\n次の手順:\n",
    "  1. RStudio を再起動する\n",
    "  2. メニューの Addins から「Stat Consultant: 起動」を選ぶ\n",
    "  3. ブラウザでチャット画面が開いたら、歯車アイコンから\n",
    "     ご自身の API キーを設定する\n"
  )
})
