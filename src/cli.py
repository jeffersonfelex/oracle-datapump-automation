"""Menu interativo e argumentos de linha de comando."""

import os
import sys
import argparse


def _run_interactive_menu():
    """Mostra o menu e preenche sys.argv com os argumentos equivalentes."""
    print("\n" + "=" * 70)
    print("  ATUALIZAÇÃO DAS BASES ORACLE - SISTEMAS CORPORATIVOS")
    print("=" * 70)
    print("Nenhum parâmetro de linha de comando informado.")
    print("Escolha uma opção:")
    print("  [1] Processar TODOS os sistemas corporativos em PRODUÇÃO")
    print("  [2] Processar um sistema corporativo específico (ex: VENDAS, COMPRAS, FINANCEIRO)")
    print("  [3] Retomar/Continuar em PRODUÇÃO a partir de um sistema (ex: FINANCEIRO, LOGISTICA)")
    print("  [4] Simulação (Dry-Run) para TODOS os sistemas")
    print("  [5] Simulação (Dry-Run) para um sistema específico")
    print("  [0] Sair")
    print("=" * 70)

    opcao = input("Opção desejada [1-5, ou 0 para sair]: ").strip()
    if opcao == "1":
        sys.argv.append("--all")
        _maybe_add_teste_flag()
    elif opcao == "2":
        sis = input("Digite a sigla do sistema (ex: VENDAS, COMPRAS, FINANCEIRO): ").strip().upper()
        if not sis:
            print("Operação cancelada.")
            sys.exit(0)
        sys.argv.extend(["--sistema", sis])
        _maybe_add_teste_flag()
    elif opcao == "3":
        sis = input("Digite a sigla a partir de onde continuar (ex: FINANCEIRO, LOGISTICA): ").strip().upper()
        if not sis:
            print("Operação cancelada.")
            sys.exit(0)
        sys.argv.extend(["--all", "--from-sistema", sis])
        _maybe_add_teste_flag()
    elif opcao == "4":
        sys.argv.extend(["--all", "--dry-run"])
    elif opcao == "5":
        sis = input("Digite a sigla do sistema para simulação (ex: VENDAS): ").strip().upper()
        if not sis:
            print("Operação cancelada.")
            sys.exit(0)
        sys.argv.extend(["--sistema", sis, "--dry-run"])
    else:
        print("Saindo...")
        sys.exit(0)


def _maybe_add_teste_flag():
    """Pergunta se a execução real deve rodar em modo teste (sufixo nos arquivos)."""
    resp = input(
        "Executar em MODO TESTE (sufixo nos arquivos .dmp/.dmp.gz/.log)? [s/N]: "
    ).strip().lower()
    if resp == "s":
        sys.argv.append("--teste")
        print("Modo teste ATIVO: os arquivos enviados/gerados no Oracle usarão o sufixo de teste.")


def build_arg_parser(default_config_path: str) -> argparse.ArgumentParser:
    """Monta o parser de argumentos de linha de comando da automação."""
    parser = argparse.ArgumentParser(
        description="Automação de Atualização das Bases Oracle dos Sistemas Corporativos"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--sistema",
        type=str,
        help="Sigla do sistema corporativo específico (ex: VENDAS, COMERCIAL, FINANCEIRO, RH)"
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Processa todos os sistemas corporativos configurados"
    )

    parser.add_argument(
        "--from-sistema", "--from",
        dest="from_sistema",
        type=str,
        default=None,
        help="Inicia ou retoma o processamento a partir desta sigla de sistema (ex: --from FINANCEIRO ou --from LOGISTICA)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Modo de simulação (não executa comandos destrutivos nem imports reais)"
    )
    parser.add_argument(
        "--skip-origem",
        action="store_true",
        help="Pula o download do servidor de origem e usa arquivos já presentes no disco local"
    )
    parser.add_argument(
        "--teste",
        action="store_true",
        help=(
            "Modo teste: insere o sufixo configurado (teste.sufixo em config.yaml, padrão "
            "'_teste') nos arquivos .dmp/.dmp.gz enviados ao Oracle e no .log gerado pelo "
            "impdp, para validar o fluxo completo com arquivos claramente identificáveis "
            "antes de assumir produção. Sem esta flag, garante os nomes de produção (remove "
            "o sufixo se tiver sobrado de uma execução de teste anterior)."
        )
    )
    parser.add_argument(
        "--periodo",
        type=str,
        default=None,
        help="Sobrescreve o período ANO-MÊS (ex: 2026-09). Por padrão usa a data do export."
    )
    parser.add_argument(
        "--config",
        type=str,
        default=default_config_path,
        help="Caminho para o arquivo config.yaml customizado"
    )
    return parser


def parse_args(current_dir: str) -> argparse.Namespace:
    """Abre o menu quando não há argumentos e devolve os argumentos interpretados."""
    if len(sys.argv) == 1:
        _run_interactive_menu()

    default_config_path = os.path.join(current_dir, "config", "config.yaml")
    parser = build_arg_parser(default_config_path)
    return parser.parse_args()
