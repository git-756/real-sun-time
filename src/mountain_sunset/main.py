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
    """Open-Elevation APIを使用して標高を取得"""
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

def get_horizon_elevation_angle(obs_lat, obs_lon, obs_alt, azimuth, check_distance_km=50, step_km=0.5):
    """
    指定方位にある地形の最大仰角を計算
    修正点:
    1. step_km を引数で受け取るように変更
    2. 自分より低い地形でも、地平線より高ければ（または視界を遮れば）角度を計算するよう修正
    """
    # 初期値は非常に低い角度（見下ろす角度）にしておく
    max_angle = -90.0
    
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

    # APIリクエストの分割処理（点が多すぎるとエラーになる可能性があるため100点ずつ）
    chunk_size = 100
    all_results = []
    
    url = 'https://api.open-elevation.com/api/v1/lookup'

    for i in range(0, len(points), chunk_size):
        chunk = points[i:i + chunk_size]
        payload = {'locations': chunk}
        try:
            r = requests.post(url, json=payload, timeout=20)
            if r.status_code == 200:
                all_results.extend(r.json()['results'])
            else:
                print(f"API Warning: Status {r.status_code}")
        except Exception as e:
            print(f"Elevation API Error: {e}")
            continue

    # 仰角の計算
    has_valid_data = False
    
    for i, item in enumerate(all_results):
        terrain_alt = item['elevation']
        dist_m = distances[i] * 1000.0
        
        # 地球の曲率を考慮しない簡易計算（近距離ならOK）
        relative_height = terrain_alt - obs_alt
        
        # arctanで角度を求める（自分より低ければマイナスの値になる＝見下ろす）
        angle = math.degrees(math.atan(relative_height / dist_m))
        
        if angle > max_angle:
            max_angle = angle
            has_valid_data = True

    # データが一つも取れなかった、あるいは計算結果が極端に低い場合は0（地平線）を返す安全策
    if not has_valid_data or max_angle == -90.0:
        return 0.0
        
    return max_angle

def setup_observer(target_date_obj, lat, lon):
    """観測者の初期設定と標高取得"""
    observer = ephem.Observer()
    observer.lat = str(lat)
    observer.lon = str(lon)
    
    print("観測地点の標高を取得中...")
    my_elevation = get_terrain_altitude(lat, lon)
    observer.elevation = my_elevation
    print(f"観測地点: 標高 {my_elevation}m")
    
    return observer, my_elevation

def calculate_actual_sunset(observer, my_elevation, target_date_obj, lat, lon, settings):
    """日の入り計算"""
    print("\n【日の入り(Sunset)の計算】")
    
    target_noon_jst = datetime.datetime.combine(target_date_obj, datetime.time(12, 0)).replace(tzinfo=JST)
    observer.date = target_noon_jst.astimezone(datetime.timezone.utc)
    
    sun = ephem.Sun()
    try:
        standard_sunset = observer.next_setting(sun)
    except (ephem.AlwaysUpError, ephem.NeverUpError):
        return None

    current_check_time = standard_sunset.datetime()
    std_sunset_jst = current_check_time.replace(tzinfo=datetime.timezone.utc).astimezone(JST)
    print(f"標準的な日の入り(地平線): {std_sunset_jst.strftime('%H:%M:%S')} (JST)")

    step_minutes = settings.get('step_minutes', 2)
    check_dist = settings.get('check_distance_km', 20)
    step_dist = settings.get('step_km', 2.0) # 設定から読み込み
    
    max_rewind_limit = datetime.timedelta(minutes=120)
    elapsed_rewind = datetime.timedelta(0)
    found_time = None

    while elapsed_rewind < max_rewind_limit:
        observer.date = current_check_time
        sun.compute(observer)
        sun_az = math.degrees(sun.az)
        sun_alt = math.degrees(sun.alt)
        
        terrain_angle = get_horizon_elevation_angle(lat, lon, my_elevation, sun_az, 
                                                  check_distance_km=check_dist, step_km=step_dist)
        
        jst_time = current_check_time.replace(tzinfo=datetime.timezone.utc).astimezone(JST)
        print(f"時刻: {jst_time.strftime('%H:%M')} | 方位: {sun_az:.1f}° | 高度: {sun_alt:.2f}° | 山仰角: {terrain_angle:.2f}°")
        
        if sun_alt > terrain_angle:
            print(f"★ 太陽が山の上に顔を出しました（遡り完了）")
            found_time = current_check_time + datetime.timedelta(minutes=step_minutes)
            break
        
        current_check_time -= datetime.timedelta(minutes=step_minutes)
        elapsed_rewind += datetime.timedelta(minutes=step_minutes)

    if found_time is None:
        found_time = standard_sunset.datetime()
    
    return found_time

def calculate_actual_sunrise(observer, my_elevation, target_date_obj, lat, lon, settings):
    """日の出計算"""
    print("\n【日の出(Sunrise)の計算】")
    
    target_midnight_jst = datetime.datetime.combine(target_date_obj, datetime.time(0, 0)).replace(tzinfo=JST)
    observer.date = target_midnight_jst.astimezone(datetime.timezone.utc)
    
    sun = ephem.Sun()
    try:
        standard_sunrise = observer.next_rising(sun)
    except (ephem.AlwaysUpError, ephem.NeverUpError):
        return None

    current_check_time = standard_sunrise.datetime()
    std_sunrise_jst = current_check_time.replace(tzinfo=datetime.timezone.utc).astimezone(JST)
    print(f"標準的な日の出(地平線): {std_sunrise_jst.strftime('%H:%M:%S')} (JST)")

    step_minutes = settings.get('step_minutes', 2)
    check_dist = settings.get('check_distance_km', 20)
    step_dist = settings.get('step_km', 2.0) # 設定から読み込み

    max_forward_limit = datetime.timedelta(minutes=120)
    elapsed_forward = datetime.timedelta(0)
    found_time = None

    while elapsed_forward < max_forward_limit:
        observer.date = current_check_time
        sun.compute(observer)
        sun_az = math.degrees(sun.az)
        sun_alt = math.degrees(sun.alt)
        
        terrain_angle = get_horizon_elevation_angle(lat, lon, my_elevation, sun_az, 
                                                  check_distance_km=check_dist, step_km=step_dist)
        
        jst_time = current_check_time.replace(tzinfo=datetime.timezone.utc).astimezone(JST)
        print(f"時刻: {jst_time.strftime('%H:%M')} | 方位: {sun_az:.1f}° | 高度: {sun_alt:.2f}° | 山仰角: {terrain_angle:.2f}°")
        
        if sun_alt > terrain_angle:
            print(f"★ 太陽が山から出ました！")
            found_time = current_check_time
            break
        
        current_check_time += datetime.timedelta(minutes=step_minutes)
        elapsed_forward += datetime.timedelta(minutes=step_minutes)

    if found_time is None:
        print("計算範囲内で日の出を確認できませんでした。")
        found_time = standard_sunrise.datetime()
    
    return found_time

if __name__ == "__main__":
    config = load_config("config.yaml")
    
    lat = config['location']['latitude']
    lon = config['location']['longitude']
    date_conf = config['target']['date']
    mode = config.get('mode', 'sunset')
    settings = config['settings']

    if date_conf == "today":
        target_date = datetime.date.today()
    else:
        try:
            target_date = datetime.datetime.strptime(date_conf, "%Y-%m-%d").date()
        except ValueError:
            sys.exit("エラー: 日付形式不正")

    print(f"計算対象日: {target_date}, 座標: {lat}, {lon}, モード: {mode}")
    
    observer, my_elevation = setup_observer(target_date, lat, lon)

    results = []

    if mode in ["sunrise", "both"]:
        res_rise = calculate_actual_sunrise(observer, my_elevation, target_date, lat, lon, settings)
        if res_rise:
            res_rise_jst = res_rise.replace(tzinfo=datetime.timezone.utc).astimezone(JST)
            results.append(f"日の出: {res_rise_jst.strftime('%H:%M:%S')} (JST)")

    if mode in ["sunset", "both"]:
        res_set = calculate_actual_sunset(observer, my_elevation, target_date, lat, lon, settings)
        if res_set:
            res_set_jst = res_set.replace(tzinfo=datetime.timezone.utc).astimezone(JST)
            results.append(f"日の入り: {res_set_jst.strftime('%H:%M:%S')} (JST)")

    print("\n" + "="*40)
    print(f"【計算結果】 {target_date} @ {lat},{lon}")
    for r in results:
        print(r)
    print("="*40)