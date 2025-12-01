import ephem
import math
import requests
import datetime
import yaml  # 追加
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
    """メイン計算ロジック"""
    
    # 1. 観測者(Observer)の設定
    observer = ephem.Observer()
    observer.lat = str(lat)
    observer.lon = str(lon)
    
    # 標高取得
    print("観測地点の標高を取得中...")
    my_elevation = get_terrain_altitude(lat, lon)
    observer.elevation = my_elevation
    print(f"観測地点: 標高 {my_elevation}m")

    # 2. 計算基準時刻の設定
    # configの日付(JST)の正午を基準にして、その日の日没を探す
    target_noon_jst = datetime.datetime.combine(target_date_obj, datetime.time(12, 0)).replace(tzinfo=JST)
    target_noon_utc = target_noon_jst.astimezone(datetime.timezone.utc)
    
    observer.date = target_noon_utc

    # 3. 標準的な日の入り時刻（地平線）
    sun = ephem.Sun()
    try:
        standard_sunset = observer.next_setting(sun)
    except ephem.AlwaysUpError:
        print("太陽が沈まない日（白夜など）です。")
        return None
    except ephem.NeverUpError:
        print("太陽が昇らない日（極夜など）です。")
        return None

    std_sunset_dt = standard_sunset.datetime().replace(tzinfo=datetime.timezone.utc)
    print(f"標準的な日の入り(地平線): {std_sunset_dt.astimezone(JST).strftime('%Y-%m-%d %H:%M:%S')} (JST)")

    # 4. 地形考慮の計算ループ
    # 標準日没の90分前からチェック開始
    current_check_time = standard_sunset.datetime() - datetime.timedelta(minutes=90)
    end_check_time = standard_sunset.datetime() + datetime.timedelta(minutes=10)
    
    step_minutes = settings.get('step_minutes', 2)
    check_dist = settings.get('check_distance_km', 20)
    
    actual_sunset_time = None
    
    print("\n--- 地形との交差判定を開始 ---")
    
    while current_check_time < end_check_time:
        observer.date = current_check_time
        sun.compute(observer)
        
        sun_az = math.degrees(sun.az)
        sun_alt = math.degrees(sun.alt)
        
        if sun_alt < 0:
            actual_sunset_time = current_check_time
            print("既に地平線の下に沈んでいます。")
            break

        terrain_angle = get_horizon_elevation_angle(lat, lon, my_elevation, sun_az, check_distance_km=check_dist, step_km=2.0)
        
        jst_time = current_check_time.replace(tzinfo=datetime.timezone.utc).astimezone(JST)
        print(f"時刻(JST): {jst_time.strftime('%H:%M')} | 太陽方位: {sun_az:.1f}° | 太陽高度: {sun_alt:.2f}° | 地形仰角: {terrain_angle:.2f}°")
        
        if sun_alt <= terrain_angle:
            actual_sunset_time = current_check_time
            print(f"★ 山に隠れました！")
            break
            
        current_check_time += datetime.timedelta(minutes=step_minutes)

    return actual_sunset_time

if __name__ == "__main__":
    # 設定ファイルの読み込み
    config = load_config("config.yaml")
    
    lat = config['location']['latitude']
    lon = config['location']['longitude']
    date_str = config['target']['date']
    settings = config['settings']

    # 日付文字列をパース
    try:
        target_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        print("エラー: 日付の形式が正しくありません。YYYY-MM-DD形式で指定してください。")
        sys.exit(1)

    print(f"計算対象日: {target_date}, 座標: {lat}, {lon}")
    
    real_sunset_utc = calculate_actual_sunset(target_date, lat, lon, settings)

    if real_sunset_utc:
        if isinstance(real_sunset_utc, datetime.datetime):
             real_sunset_jst = real_sunset_utc.replace(tzinfo=datetime.timezone.utc).astimezone(JST)
        else:
             real_sunset_jst = real_sunset_utc.datetime().replace(tzinfo=datetime.timezone.utc).astimezone(JST)
             
        print(f"\n予想される地形考慮後の日の入り時刻: {real_sunset_jst.strftime('%Y/%m/%d %H:%M:%S')} (JST)")
    else:
        print("計算範囲内で日の入りを確認できませんでした。")