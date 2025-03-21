import streamlit as st
import requests
import xml.etree.ElementTree as ET
import pandas as pd
import time
import datetime
import folium
from folium.plugins import MarkerCluster
from geopy.geocoders import Nominatim
import altair as alt

@st.cache_data(show_spinner=False)
def get_coordinates(address):
    """
    geopy의 Nominatim을 사용해 주소를 위도/경도로 변환합니다.
    """
    geolocator = Nominatim(user_agent="seoul_real_estate_app")
    try:
        location = geolocator.geocode(address)
        # Nominatim 사용 정책에 따라 요청 간 딜레이 적용
        time.sleep(1)
        if location:
            return (location.latitude, location.longitude)
    except Exception as e:
        st.error(f"Geocoding error for {address}: {e}")
    return None

def query_real_estate(api_key, district, dong, start=1, end=1000):
    """
    서울시 부동산 실거래가 API에서 XML 데이터를 가져와,
    자치구(필수)와 (법정동이 입력된 경우) 법정동이 포함된 행만 필터링하여 반환합니다.
    """
    base_url = f"http://openapi.seoul.go.kr:8088/{api_key}/xml/tbLnOpendataRtmsV/{start}/{end}"
    try:
        response = requests.get(base_url)
        response.raise_for_status()
    except Exception as e:
        st.error(f"API 호출 실패: {e}")
        return []
    
    root = ET.fromstring(response.content)
    rows = root.findall('.//row')
    
    filtered_results = []
    for row in rows:
        cgg_nm = row.find('CGG_NM').text if row.find('CGG_NM') is not None else ""
        stdg_nm = row.find('STDG_NM').text if row.find('STDG_NM') is not None else ""
        # 자치구는 필수이며, 법정동은 입력된 경우에만 필터링합니다.
        if district in cgg_nm and (not dong or dong in stdg_nm):
            data = {
                "접수연도": row.find('RCPT_YR').text if row.find('RCPT_YR') is not None else "",
                "자치구명": cgg_nm,
                "법정동명": stdg_nm,
                "본번": row.find("MNO").text if row.find("MNO") is not None else "",
                "부번": row.find("SNO").text if row.find("SNO") is not None else "",
                "건물명": row.find('BLDG_NM').text if row.find('BLDG_NM') is not None else "",
                "계약일": row.find('CTRT_DAY').text if row.find('CTRT_DAY') is not None else "",
                "물건금액(만원)": row.find('THING_AMT').text if row.find('THING_AMT') is not None else "",
                "건물면적(㎡)": row.find('ARCH_AREA').text if row.find('ARCH_AREA') is not None else ""
            }
            filtered_results.append(data)
    
    return filtered_results

def convert_data(results):
    """
    리스트 형태의 결과를 DataFrame으로 변환하고,
    계약일을 datetime, 물건금액 및 건물면적을 숫자로 변환한 후,
    단가(만원/㎡)를 계산하여 새로운 컬럼으로 추가합니다.
    """
    df = pd.DataFrame(results)
    if df.empty:
        return df
    # 계약일: YYYYMMDD 형식을 datetime으로 변환
    df['계약일'] = pd.to_datetime(df['계약일'], format='%Y%m%d', errors='coerce')
    # 물건금액과 건물면적을 숫자로 변환
    df['물건금액(만원)'] = pd.to_numeric(df['물건금액(만원)'], errors='coerce')
    df['건물면적(㎡)'] = pd.to_numeric(df['건물면적(㎡)'], errors='coerce')
    # 단가(만원/㎡) 계산
    df['단가(만원/㎡)'] = df.apply(
        lambda row: row['물건금액(만원)'] / row['건물면적(㎡)']
        if row['건물면적(㎡)'] and row['건물면적(㎡)'] > 0 else None, axis=1)
    return df

def download_button(df):
    """
    DataFrame을 CSV 파일로 변환해 다운로드할 수 있는 버튼 생성.
    """
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="데이터 CSV 다운로드",
        data=csv,
        file_name="seoul_real_estate.csv",
        mime="text/csv"
    )

def main():
    st.title("서울시 부동산 실거래가 조회 & 분석")
    
    # 인증키 (본인의 서울시 실거래 API 키로 교체)
    real_estate_api_key = "626e626f4a676b7739357a62577661"
    
    st.sidebar.header("검색 조건")
    district = st.sidebar.text_input("자치구명 (예: 강서구)")
    dong = st.sidebar.text_input("법정동명 (예: 화곡동) - 선택사항")
    start = st.sidebar.number_input("시작 행 번호", value=1, min_value=1)
    end = st.sidebar.number_input("종료 행 번호", value=1000, min_value=1)
    
    if st.sidebar.button("조회"):
        if not district:
            st.warning("자치구명을 입력하세요.")
            return
        
        with st.spinner("실거래 데이터를 조회중입니다..."):
            results = query_real_estate(real_estate_api_key, district, dong, start, end)
        if not results:
            st.info("해당 조건의 실거래 데이터가 없습니다.")
            return
        
        df = convert_data(results)
        st.subheader("실거래가 조회 결과")
        st.dataframe(df)
        download_button(df)
        
        # 계약일을 기준으로 날짜 필터 적용 (데이터에 계약일이 존재하는 경우)
        if not df.empty and df['계약일'].notnull().any():
            min_date = df['계약일'].min().date()
            max_date = df['계약일'].max().date()
            date_range = st.sidebar.date_input("계약일 범위 선택", [min_date, max_date])
            if len(date_range) == 2:
                df = df[(df['계약일'] >= pd.Timestamp(date_range[0])) & 
                        (df['계약일'] <= pd.Timestamp(date_range[1]))]
        
        # 요약 KPI 표시 (총 거래 건수, 평균 거래가, 평균 단가)
        st.subheader("요약 지표")
        kpi1, kpi2, kpi3 = st.columns(3)
        total_count = len(df)
        avg_price = df['물건금액(만원)'].mean() if not df['물건금액(만원)'].empty else 0
        avg_unit_price = df['단가(만원/㎡)'].mean() if not df['단가(만원/㎡)'].empty else 0
        kpi1.metric(label="총 거래 건수", value=f"{total_count:,}")
        kpi2.metric(label="평균 거래가(만원)", value=f"{avg_price:,.0f}만원")
        kpi3.metric(label="평균 단가(만원/㎡)", value=f"{avg_unit_price:,.2f}만원/㎡")
        
        # 1. 거래 추이 분석 (월별 평균 평당가 변화)
        st.subheader("거래 추이 분석 (월별 평당가 변화)")
        df_time = df.dropna(subset=['계약일', '단가(만원/㎡)']).copy()
        if not df_time.empty:
            df_time['년월'] = df_time['계약일'].dt.to_period('M').dt.to_timestamp()
            df_group = df_time.groupby('년월')['단가(만원/㎡)'].mean().reset_index()
            line_chart = alt.Chart(df_group).mark_line(point=True).encode(
                x=alt.X('년월:T', title="계약일(월)"),
                y=alt.Y('단가(만원/㎡):Q', title="평당가(만원/㎡)")
            ).properties(width=700, height=400)
            st.altair_chart(line_chart, use_container_width=True)
        else:
            st.info("계약일 및 단가 정보가 부족하여 거래 추이 분석을 수행할 수 없습니다.")
        
        # 2. 건물면적 대비 가격 분석 (단가 분포 & 산점도)
        st.subheader("건물면적 대비 가격 분석")
        df_analysis = df.dropna(subset=['단가(만원/㎡)', '건물면적(㎡)']).copy()
        if not df_analysis.empty:
            hist = alt.Chart(df_analysis).mark_bar().encode(
                alt.X('단가(만원/㎡):Q', bin=alt.Bin(maxbins=30), title="단가(만원/㎡)"),
                alt.Y('count()', title="거래 건수")
            ).properties(width=350, height=300)
            scatter = alt.Chart(df_analysis).mark_circle(size=60).encode(
                x=alt.X('건물면적(㎡):Q', title="건물면적(㎡)"),
                y=alt.Y('단가(만원/㎡):Q', title="단가(만원/㎡)"),
                tooltip=['건물명', '물건금액(만원)', '건물면적(㎡)', '단가(만원/㎡)']
            ).properties(width=350, height=300)
            col1, col2 = st.columns(2)
            with col1:
                st.altair_chart(hist, use_container_width=True)
            with col2:
                st.altair_chart(scatter, use_container_width=True)
        else:
            st.info("분석할 수 있는 단가 및 건물면적 데이터가 부족합니다.")
        
        # 3. 상위 거래 TOP 5 하이라이트 (거래금액 기준)
        st.subheader("상위 거래 TOP 5 하이라이트")
        df_top5 = df.dropna(subset=['물건금액(만원)']).copy()
        df_top5['물건금액(만원)'] = pd.to_numeric(df_top5['물건금액(만원)'], errors='coerce')
        top5 = df_top5.nlargest(5, '물건금액(만원)')
        if not top5.empty:
            cols = st.columns(5)
            for idx, (_, row) in enumerate(top5.iterrows()):
                with cols[idx]:
                    st.markdown(f"### {idx+1}위")
                    st.metric(label=row['건물명'] if row['건물명'] else "건물명 없음",
                              value=f"{int(row['물건금액(만원)']):,}만원")
                    st.write(f"면적: {row['건물면적(㎡)']} ㎡")
                    st.write(f"계약일: {row['계약일'].strftime('%Y-%m-%d') if pd.notnull(row['계약일']) else 'N/A'}")
        else:
            st.info("상위 거래 데이터를 찾을 수 없습니다.")
        
        # 4. 지도 시각화: Folium의 MarkerCluster 활용
        st.subheader("거래 위치 지도")
        with st.spinner("지도 데이터를 조회중입니다..."): 
            map_data = []
            for idx, row in df.iterrows():
                if row['본번']:
                    if row['부번'] in ['0000', '', None]:
                        address = f"서울특별시 {row['자치구명']} {row['법정동명']} {row['본번']}"
                    else:
                        address = f"서울특별시 {row['자치구명']} {row['법정동명']} {row['본번']}-{row['부번']}"
                    coords = get_coordinates(address)
                    if coords:
                        map_data.append({
                            "lat": coords[0],
                            "lon": coords[1],
                            "건물명": row['건물명'],
                            "주소": address,
                            "물건금액(만원)": row['물건금액(만원)'],
                            "단가(만원/㎡)": row['단가(만원/㎡)']
                        })
            if map_data:
                avg_lat = sum([d["lat"] for d in map_data]) / len(map_data)
                avg_lon = sum([d["lon"] for d in map_data]) / len(map_data)
                m = folium.Map(location=[avg_lat, avg_lon], zoom_start=12)
                marker_cluster = MarkerCluster().add_to(m)
                for d in map_data:
                    popup_html = (
                        f"<b>{d['건물명']}</b><br>"
                        f"주소: {d['주소']}<br>"
                        f"거래가: {int(d['물건금액(만원)']) if d['물건금액(만원)'] else 'N/A'}만원<br>"
                        f"단가: {round(d['단가(만원/㎡)'], 2) if d['단가(만원/㎡)'] else 'N/A'}만원/㎡"
                    )
                    folium.Marker(
                        location=[d["lat"], d["lon"]],
                        tooltip=d["건물명"] if d["건물명"] else "건물명 없음",
                        popup=popup_html
                    ).add_to(marker_cluster)
            
                st.components.v1.html(m._repr_html_(), height=500)
            else:
                st.info("지도에 표시할 위치 데이터가 없습니다.")

if __name__ == "__main__":
    main()
