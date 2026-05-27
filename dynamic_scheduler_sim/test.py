# c:\Users\yuhaoran\Desktop\repo\dynamic_scheduler\src\check.py
import ast
import pathlib

src = pathlib.Path(__file__).parent / "models.py"
tree = ast.parse(src.read_text(encoding="utf-8"))

print("=" * 50)
print("models.py 顶层定义（类 / 函数 / 变量）")
print("=" * 50)

# ✅ 只遍历顶层节点，不深入类内部
for node in ast.iter_child_nodes(tree):  # ← iter_child_nodes 而非 walk
    if isinstance(node, ast.ClassDef):
        print(f"\n📦 类: {node.name}")
        # 打印类的成员
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef):
                deco_names = [
                    (
                        d.id
                        if isinstance(d, ast.Name)
                        else d.attr if isinstance(d, ast.Attribute) else "?"
                    )
                    for d in child.decorator_list
                ]
                tag = f"[@{','.join(deco_names)}]" if deco_names else ""
                print(f"    ├── 方法 {tag}: {child.name}")

    elif isinstance(node, ast.FunctionDef):
        print(f"\n⚙️  顶层函数: {node.name}")

    elif isinstance(node, (ast.Assign, ast.AnnAssign)):
        print(f"\n📌 顶层变量")
