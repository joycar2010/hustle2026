msg = "服务的实例已在运行中"
print("Test 1 - Direct Chinese:", "实例" in msg)
print("Test 2 - Unicode escape:", "\u5b9e\u4f8b" in msg)
print("Test 3 - Message:", repr(msg))
