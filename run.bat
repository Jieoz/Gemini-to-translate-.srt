@echo off
REM =================================================================
REM == SRT Translator - One-Click Launcher ==
REM == ˫���˽ű���ͬʱ������˺�ǰ�˷��� ==
REM =================================================================

REM ���õ�ǰ���ڵı���
title SRT Translator Launcher

echo.
echo =============================================
echo   SRT ������ ����������...
echo =============================================
echo.
echo �����������µ�����ڣ�����ر����ǡ�
echo.

REM --- ���� FastAPI ��˷��� ---
REM ʹ�� start �������´��������� uvicorn
REM cmd /k �ᱣ���´���������ִ�к��Զ��رգ�����鿴��־
echo [1/2] �������� FastAPI ��˷���...
start "SRT_Backend" cmd /k uvicorn main:app --host "0.0.0.0" --port 8000

REM --- �ȴ������ӣ�ȷ����˷������㹻��ʱ���ʼ�� ---
echo.
echo �ȴ� 3 ������ȷ������ȶ�...
timeout /t 3 /nobreak >nul

REM --- ���� Streamlit ǰ�˷��� ---
REM ͬ�������´��������� Streamlit
echo [2/2] �������� Streamlit ǰ�˽���...
start "SRT_Frontend" cmd /k streamlit run webui.py

echo.
echo =============================================
echo   ���з�����������
echo =============================================
echo.
echo - ��˷��������� "SRT_Backend" �����С�
echo - ǰ�˽��������� "SRT_Frontend" �����С�
echo - ���������Ӧ�û��Զ���Ӧ��ҳ�档
echo.
echo �����ڿ��Թر���������������ˡ�
echo.

REM ��ͣһ�£����û����Կ����������Ϣ
pause
