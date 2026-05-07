
# 概要

PS5ゲーム「Gran Turismo 7」のUDP通信機能を利用して、マイコンと連携し演出によって走行体験を向上させる。
またPCが通信ハブとなり、走行データ処理、複数台のデバイスの統合制御やレース時の演出連携などを行う。

## デバイス

### PlayStation 5
- Gran Turismo 7
- PCと同一LAN内
### PC
- Python 3.8.10
- 複数デバイスと接続し、ハブとして機能する
- 主要ライブラリ...
	- GT7通信 > https://pypi.org/project/granturismo/ (0.0.10)
	- シリアル通信 > `pyserial` 
- 簡易的なGUIをNiceGUIで実装する
- 走行データをCSVで記録する
### マイコン
- ESP32 - C++
- Serial 115,200 bps
- 固定IDをマイコンごとに設定
- 主要ライブラリ...
	- LEDテープ制御 > `FastLED`

#### セットアップ

環境固有の設定（デバイスID、LED ピンなど）はテンプレートから初期化します：

```bash
cd gt7_seat_esp/include
cp config.h.example config.h
cd ../..
cp gt7_seat_esp/platformio.ini.example gt7_seat_esp/platformio.ini
```

その後、`config.h` と `platformio.ini` を必要に応じて編集します（git 追跡外）。


---
# 本番の想定

## 接続

**PS5×4**　→UDP→　**PC (ハブ)**　→Serial→　**ESP32×4 (+会場演出1)**
- **PS5 - PC** ...　PC → Heartbeat ｜ PS5 → Telemetry （ライブラリ使用）
- **PC - ESP32** ...　PC → Data, Event, Pong ｜ ESP32 → Ping

## PC
### 通信
- n台のPS5 (IPアドレス入力) と
  n台のESP32 (接続されたマイコンごとの固定ID受信)を紐づける
- ESP32とは20Hz、115,200 bpsでシリアル通信を行う
### 制御
- 複数UDP受付→同時処理→複数マイコン制御
- できるだけESP32のデータ処理負荷を下げる
- レースの場合、事前に対戦マシン登録を行う。
### UI
- NiceGUI
- 各デバイスの接続、接続状態表示
- PS5同士の連携（レース用）

## ESP32 (マイコン)
### 通信
- Speed等の継続的な走行状態の更新受付　
- クラッシュやラップ経過、レース順位更新などのトリガーイベント受付
- これらは同時に複数種類が送られてくる
- Heartbeat（固定ID付のPing）を送る
### 制御
- アニメーションの演算、出力の制御を行う
- LED strip (FastLEDライブラリを使用)
- PWM制御可能ファン (回転数の厳密な制御は不要)

## 取得可能なデータ

全データは [ライブラリ説明ページ](https://pypi.org/project/granturismo/) を参照

取得した値をESP32にそのまま連続データとして流したり、加工して流したり、値の変化量に応じてイベントトリガーとして判断したり。
データの取捨選択と処理責任の分散が必要。

### 使えそうな主要データ抜粋

**Body**
- float: `car_speed` in meters per second
- Vector: `velocity` in meters per second (needs direction research)
    - float: `x` 
    - float: `y` 
    - float: `z` 
- Vector: `angular_velocity` radians per second
    - float: `x`
    - float: `y`
    - float: `z`

**Driving**
- float: `engine_rpm` 0-?
- Bounds: `rpm_alert`
    - float: `min` 0-?
    - float: `max` 0-?
- int: `throttle` between 0-255-   
- int: `brake` between 0-255
- float: `turbo_boost` this value - 1 gives the Turbo Boost display
- Optional(int): `current_gear` 0-4: current gear, 0 is reverse, None is neutral

**Racing**
- Flags: `flags`
	- bool: `in_race`
- Optional(int): `cars_in_race` only available before race starts, otherwise None
- Optional(int): `lap_count` None if not in race
- Optional(int): `laps_in_race` None if not in race
- Optional(int): `best_lap_time` In milliseconds. None if not in race, or no lap complete.
- Optional(int): `last_lap_time` In milliseconds. None if no lap completed


---

# 開発｜実装

## 序盤の開発

まずは土台を整える。

### 開発ツール
> PS5が無くても、過去に記録した走行データをトレースして実験できるようにする。
- [x] 走行データをタイムスタンプ付きでDBに記録
	- 解析・分解したものを記録する必要はない　あくまでトレース用
	  ただし、テレメトリを解析する関数をライブラリから流用できない場合、関数の実装コストが高いため解析後のデータをDBに記録してもよい
- [ ] 走行データの記録をトレース、PS4のUDP通信時と同等の機能を持たせる
	- 実際に通信する必要はない　PCの処理側で疑似的に再現するだけで十分
	- PC側では、通信時とトレース時の２方式でデータ入力を受け付ける必要がある
### PC
> ハブとして両デバイスの最低限通信機能を確立。
- [ ] 複数デバイスを取り扱う想定のデータ構造
- [ ] 通信の確立と維持
	- PS5にHeartbeatを送るとテレメトリが返ってくる
	- 注意：PS5はコース上以外（メニュー画面等）では信号を返さない
	- ESP32からPingとともに固定IDが送られてくるので、識別しつつPong
- [x] PC側でPS5の走行データを取得する
	- 必要な情報のみ抽出して処理する
- [x] 走行データをCSVに記録する
	- タイムスタンプ付き　上記 [[#使えそうな主要データ抜粋]] を記録する
- [x] ESP32に必要なデータを送信する
	- 負荷軽減のため、Pythonの `struct.pack`を使用したバイナリプロトコル化とレート制限をかける
	- 必要な情報のみ　処理後のデータ/イベントを送信する
### ESP32
> PCとの最低限通信機能を確立。
- [x] ステータスLED
	- 正常→消灯
	- 通信異常→点滅
	- その他の異常→点灯
- [x] シリアル通信を確立
- [x] 連続データ、トリガーイベント両方キャッチする
- [x] FastLEDで動作チェック

### デバッグデータ
> 現時点でデバッグのために扱うテストデータ

- [x] Pythonコンソール：`car_speed`, `engine_rpm`, `velocity y&z`, 
- [x] 連続データ：`car_speed` (float) - meters per second
	- `clamp ( car_speed / 50.0, 0.0, 1.0 )` を全体からの割合として、LEDをその数点灯させる
	- このケースではPCはESP32にデータをそのまま流し、ESP32がclamp処理をする
	- FastLED で 600 LED のバー表示を実装
- [x] イベント：`current_gear` (int) - 0~4 が切り替わった瞬間
	- `0:red 1:yellow 2:green 3:blue 4:cyan` でcar_speedゲージのLED色を変える
	- このケースではPCがトリガーを検知し、ESP32にデータとともにイベントを送信する

## 中盤の開発

やらない。また別のセッションで。

### PC｜走行データ処理

### PC｜フロントエンドUI

### ESP32｜LEDとファンの演出


---
