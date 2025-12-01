import ephem
import math
import requests
import datetime
import yaml
import sys
from pathlib import Path

# 日本時間(JST)の定義
JST = datetime.timezone(datetime.timedelta(hours=9))

def load_config(config_path="config.yaml"):
    """設定ファイルを読み込む"""
    path = Path(config_path)
    if not path.exists():
        print(f"エラー: 設定ファイル {config_path} が見つかりません。")
        sys.exit(1)
    
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def get_terrain_altitude(lat, lon):
    """Open-Elevation APIを使用して標高を取得 (POST版)"""
    url = 'https://api.open-elevation.com/api/v1/lookup'
    payload = {'locations': [{'latitude': lat, 'longitude': lon}]}
    try:
        r = requests.post(url, json=payload, timeout=10)
        data = r.json()
        return data['results'][0]['elevation']
    except Exception as e:
        print(f"API Error (get_terrain_altitude): {e}")
        return 0

def calculate_destination(lat, lon, distance_km, bearing_deg):
    """距離と方位から移動先の座標を計算"""
    R = 6371.0
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    bearing_rad = math.radians(bearing_deg)
    
    new_lat_rad = math.asin(math.sin(lat_rad) * math.cos(distance_km / R) +
                            math.cos(lat_rad) * math.sin(distance_km / R) * math.cos(bearing_rad))
    
    new_lon_rad = lon_rad + math.atan2(math.sin(bearing_rad) * math.sin(distance_km / R) * math.cos(lat_rad),
                                       math.cos(distance_km / R) - math.sin(lat_rad) * math.sin(new_lat_rad))
    return math.degrees(new_lat_rad), math.degrees(new_lon_rad)

def get_horizon_elevation_angle(obs_lat, obs_lon, obs_alt, azimuth, check_distance_km=20, step_km=1.0):
    """指定方位にある地形の最大仰角を計算"""
    max_angle = 0.0
    points = []
    distances = []
    
    d = step_km
    while d <= check_distance_km:
        lat, lon = calculate_destination(obs_lat, obs_lon, d, azimuth)
        points.append({"latitude": lat, "longitude": lon})
        distances.append(d)
        d += step_km

    if not points:
        return 0.0

    url = 'https://api.open-elevation.com/api/v1/lookup'
    payload = {'locations': points}
    
    try:
        r = requests.post(url, json=payload, timeout=10)
        results = r.json()['results']
        for i, item in enumerate(results):
            terrain_alt = item['elevation']
            dist_m = distances[i] * 1000.0
            relative_height = terrain_alt - obs_alt
            
            if relative_height <= 0: continue
            
            angle = math.degrees(math.atan(relative_height / dist_m))
            if angle > max_angle:
                max_angle = angle
    except Exception as e:
        print(f"Elevation API Error: {e}")
        
    return max_angle

def calculate_actual_sunset(target_date_obj, lat, lon, settings):
    """
    メイン計算ロジック（巻き戻し方式）
    標準的な日の入り時刻から時間を遡り、太陽が山から顔を出した瞬間の直後を日の入りとする。
    """
    
    # 1. 観測者設定
    observer = ephem.Observer()
    observer.lat = str(lat)
    observer.lon = str(lon)
    
    print("観測地点の標高を取得中...")
    my_elevation = get_terrain_altitude(lat, lon)
    observer.elevation = my_elevation
    print(f"観測地点: 標高 {my_elevation}m")

    # 2. 計算基準時刻の設定（正午基準）
    target_noon_jst = datetime.datetime.combine(target_date_obj, datetime.time(12, 0)).replace(tzinfo=JST)
    observer.date = target_noon_jst.astimezone(datetime.timezone.utc)

    # 3. 標準的な日の入り時刻（地平線）を計算
    sun = ephem.Sun()
    try:
        standard_sunset = observer.next_setting(sun)
    except (ephem.AlwaysUpError, ephem.NeverUpError):
        print("太陽が昇らない、または沈まない日です。")
        return None

    # スタート地点（標準日の入り）
    current_check_time = standard_sunset.datetime()
    std_sunset_jst = current_check_time.replace(tzinfo=datetime.timezone.utc).astimezone(JST)
    print(f"標準的な日の入り(地平線): {std_sunset_jst.strftime('%Y-%m-%d %H:%M:%S')} (JST)")

    # 設定読み込み
    step_minutes = settings.get('step_minutes', 2)
    check_dist = settings.get('check_distance_km', 20)
    
    print("\n--- 時間を遡って地形判定を開始 ---")
    
    # 4. 巻き戻しループ
    # 最大でも2時間(120分)遡れば十分と仮定
    max_rewind_limit = datetime.timedelta(minutes=120)
    elapsed_rewind = datetime.timedelta(0)
    
    found_sunset_time = None

    while elapsed_rewind < max_rewind_limit:
        observer.date = current_check_time
        sun.compute(observer)
        
        sun_az = math.degrees(sun.az)
        sun_alt = math.degrees(sun.alt)
        
        # 地形の仰角を取得
        terrain_angle = get_horizon_elevation_angle(lat, lon, my_elevation, sun_az, check_distance_km=check_dist, step_km=2.0)
        
        jst_time = current_check_time.replace(tzinfo=datetime.timezone.utc).astimezone(JST)
        print(f"時刻(JST): {jst_time.strftime('%H:%M')} | 太陽方位: {sun_az:.1f}° | 太陽高度: {sun_alt:.2f}° | 地形仰角: {terrain_angle:.2f}°")
        
        # 【判定ロジック】
        # これまでは「太陽高度 < 地形」を探していたが、
        # 今は「太陽高度 > 地形」になる瞬間（＝太陽が山の上に顔を出している状態）を探す。
        # その状態になったら、その「1つ前のステップ（＝まだ隠れていた時刻）」が日の入り時刻。
        
        if sun_alt > terrain_angle:
            print(f"★ 太陽が山の上に顔を出しました（遡り完了）")
            # 現在の current_check_time は「太陽が出ている」。
            # なので、山に隠れるのはこの「step_minutes 分後」あたり。
            found_sunset_time = current_check_time + datetime.timedelta(minutes=step_minutes)
            break
        
        # まだ隠れている（または地平線下）なら、時間を遡る
        current_check_time -= datetime.timedelta(minutes=step_minutes)
        elapsed_rewind += datetime.timedelta(minutes=step_minutes)

    # ループを抜けたが結果がない場合（平地で、standard_sunsetの時点で既に地形より上だった場合など）
    if found_sunset_time is None:
        # 巻き戻してもずっと隠れていた場合（深い谷底など）か、
        # 初回チェックですぐに見えてしまった場合。
        # 初回(standard_sunset)で見えていたなら、日の入りはstandard_sunsetそのもの。
        # ここでは簡易的に「標準日の入り」を返す。
        print("地形の影響を検知できなかったか、標準時刻で既に沈んでいました。")
        found_sunset_time = standard_sunset.datetime()

    return found_sunset_time

if __name__ == "__main__":
    # 設定ファイルの読み込み
    config = load_config("config.yaml")
    
    lat = config['location']['latitude']
    lon = config['location']['longitude']
    date_conf = config['target']['date']
    settings = config['settings']

    # 日付の処理: "auto" なら今日、それ以外なら指定日
    if date_conf == "auto":
        target_date = datetime.date.today()
        print(f"日付設定: auto -> {target_date} を使用します")
    else:
        try:
            target_date = datetime.datetime.strptime(date_conf, "%Y-%m-%d").date()
            print(f"日付設定: 指定日 -> {target_date} を使用します")
        except ValueError:
            print("エラー: 日付の形式が正しくありません。YYYY-MM-DD形式で指定してください。")
            sys.exit(1)

    print(f"座標: {lat}, {lon}")
    
    real_sunset_utc = calculate_actual_sunset(target_date, lat, lon, settings)

    if real_sunset_utc:
        if isinstance(real_sunset_utc, datetime.datetime):
             real_sunset_jst = real_sunset_utc.replace(tzinfo=datetime.timezone.utc).astimezone(JST)
        else:
             real_sunset_jst = real_sunset_utc.datetime().replace(tzinfo=datetime.timezone.utc).astimezone(JST)
             
        print(f"\n==============================================")
        print(f"予想される地形考慮後の日の入り時刻: {real_sunset_jst.strftime('%Y/%m/%d %H:%M:%S')} (JST)")
        print(f"==============================================")
    else:
        print("計算できませんでした。")