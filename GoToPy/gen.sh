#!/usr/bin/env bash
#
# gen.sh — Generate gRPC/Protobuf stubs for both Python and Go
#
# This script uses the protoc compiler bundled with grpc_tools,
# so you only need Python with grpcio-tools installed.
#
# Prerequisites:
#   - Python 3.10+ with grpcio-tools (pip install grpcio-tools)
#   - protoc-gen-go       (go install google.golang.org/protobuf/cmd/protoc-gen-go@latest)
#   - protoc-gen-go-grpc  (go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest)
#
# Usage: bash gen.sh

set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROTO_FILE="$ROOT_DIR/proto/calculator.proto"

# Use the protoc bundled with grpc_tools (no separate protoc install needed)
PROTOC="python -m grpc_tools.protoc"

echo "=== Generating Python stubs ==="
mkdir -p "$ROOT_DIR/server/grpc_stubs"
# Create __init__.py so it's a proper Python package
cat > "$ROOT_DIR/server/grpc_stubs/__init__.py" << 'EOF'
"""Generated gRPC stubs — do not edit manually."""
EOF

$PROTOC \
    -I "$ROOT_DIR/proto" \
    --python_out="$ROOT_DIR/server/grpc_stubs" \
    --pyi_out="$ROOT_DIR/server/grpc_stubs" \
    --grpc_python_out="$ROOT_DIR/server/grpc_stubs" \
    "$PROTO_FILE"
echo "  -> $ROOT_DIR/server/grpc_stubs/calculator_pb2.py"
echo "  -> $ROOT_DIR/server/grpc_stubs/calculator_pb2_grpc.py"

# Fix generated imports: absolute → relative (since stubs live inside grpc_stubs/ package)
echo "=== Fixing Python imports ==="
sed -i 's/^import calculator_pb2/from grpc_stubs import calculator_pb2/' \
    "$ROOT_DIR/server/grpc_stubs/calculator_pb2_grpc.py"
sed -i 's/^import calculator_pb2_grpc/from grpc_stubs import calculator_pb2_grpc/' \
    "$ROOT_DIR/server/grpc_stubs/calculator_pb2_grpc.py"
echo "  -> Fixed imports in calculator_pb2_grpc.py"

echo "=== Generating Go stubs ==="
mkdir -p "$ROOT_DIR/client/proto/calculator"

$PROTOC \
    -I "$ROOT_DIR/proto" \
    --go_out="$ROOT_DIR/client/proto/calculator" \
    --go_opt=paths=source_relative \
    --go-grpc_out="$ROOT_DIR/client/proto/calculator" \
    --go-grpc_opt=paths=source_relative \
    "$PROTO_FILE"
echo "  -> $ROOT_DIR/client/proto/calculator/calculator.pb.go"
echo "  -> $ROOT_DIR/client/proto/calculator/calculator_grpc.pb.go"

echo ""
echo "=== Done! All stubs generated. ==="
