@echo off
chcp 65001 > nul
title Agente Candidato - Conexão Segura LinkedIn
color 0A
cls
echo ======================================================================
echo    🤖 AGENTE CANDIDATO - LOGIN SEGURO DO LINKEDIN
echo ======================================================================
echo.
echo  Uma janela do navegador Chrome sera aberta na sua tela agora.
echo.
echo  Passos:
echo   1. Faca seu login normal na janela do LinkedIn.
echo   2. Se o LinkedIn pedir codigo de confirmacao no e-mail, digite-o.
echo   3. Assim que voce ver a sua pagina inicial do LinkedIn (Feed),
echo      pode simplesmente FECHAR a janela do navegador.
echo.
echo  A sua sessao ficara salva no computador para as candidaturas!
echo.
echo ======================================================================
echo  Iniciando navegador...
echo.

cd /d "%~dp0"
python main.py login linkedin

echo.
echo ======================================================================
echo  Pronto! Pressione qualquer tecla para sair desta janela.
echo ======================================================================
pause > nul
