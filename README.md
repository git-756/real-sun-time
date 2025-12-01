# Real Sun Time (山岳考慮・日の出日の入り計算機)

`real-sun-time` は、指定した座標の「地形（山など）」を考慮に入れた、より現実に即した日の出・日の入り時刻を計算するPythonスクリプトです。

通常の「地平線・水平線」基準の計算ではなく、Open-Elevation APIから周囲の標高データを取得し、太陽が山の稜線に隠れる（または現れる）正確な時刻をシミュレーションします。

---

## ✨ 主な機能

- **地形考慮**: Open-Elevation APIを使用し、指定座標から周囲（デフォルト60km）の地形データを取得して、太陽が隠れる山を探します。
- **日の入り計算**: 標準的な日の入り時刻から時間を遡り、太陽高度が山の仰角を上回る瞬間（太陽が山に沈む直前）を特定します。
- **日の出計算**: 標準的な日の出時刻から時間を進め、太陽高度が山の仰角を上回る瞬間（太陽が山から出る瞬間）を特定します。
- **柔軟な設定**: 観測地点、日付、計算モード（日の出/日の入り/両方）、地形チェックの精度などを `config.yaml` で簡単に変更できます。

---

## ⚙️ 動作要件

- Python 3.8 以上
- **PyEphem** (天体計算)
- **Requests** (API通信)
- **PyYAML** (設定ファイル読み込み)

---

## 🚀 使い方

1.  **リポジトリのクローン**
    ```bash
    git clone [リポジトリのURL]
    cd real-sun-time
    ```

2.  **依存ライブラリのインストール**
    ```bash
    # Ryeを使用している場合
    rye sync
    # pipを直接使用する場合
    # pip install ephem requests pyyaml
    ```

3.  **設定の編集**
    - `config.yaml` を開き、観測したい場所の緯度経度などを設定します。

    ```yaml
    location:
      latitude: 35.0153  # 緯度
      longitude: 138.5187 # 経度
    
    target:
      date: "today" # "today" または "2025-01-01" の形式
    
    mode: "both" # "sunrise", "sunset", "both"
    ```

4.  **スクリプトの実行**
    - ターミナルで以下のコマンドを実行します。

    ```bash
    python src/mountain_sunset/main.py
    ```

5.  **結果の確認**
    - 計算が進むにつれてコンソールに状況が表示され、最終的な「山を考慮した日の出・日の入り時刻」が出力されます。

---

## 📜 ライセンス

このプロジェクトは **MIT License** のもとで公開されています。ライセンスの全文については、[LICENSE](LICENSE) ファイルをご覧ください。

また、このプロジェクトはサードパーティ製のライブラリを利用しています。これらのライブラリのライセンス情報については、[NOTICE.md](NOTICE.md) ファイルに記載しています。

## 作成者
[Samurai-Human-Go](https://samurai-human-go.com/%e9%81%8b%e5%96%b6%e8%80%85%e6%83%85%e5%a0%b1/)
- [ブログ記事: 【Python】山に沈む夕日の時間を計算するスクリプト開発記](https://samurai-human-go.com/python-mountain-sunset-calculation/)