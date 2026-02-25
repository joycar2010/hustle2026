#!/usr/bin/env python3
"""
Clean up System.vue by removing user management functionality
"""

def clean_user_management():
    file_path = r'C:\app\hustle2026\frontend\src\views\System.vue'

    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # Skip user management tab section in template
        if "v-if=\"activeTab === 'users'\"" in line:
            # Skip until we find the next major section (version tab)
            while i < len(lines) and "v-if=\"activeTab === 'version'\"" not in lines[i]:
                i += 1
            continue

        # Skip user modal section
        if "v-if=\"showUserModal\"" in line:
            # Skip until we find TableDetailModal
            depth = 0
            started = False
            while i < len(lines):
                if "<div" in lines[i]:
                    depth += lines[i].count("<div")
                    started = True
                if "</div>" in lines[i]:
                    depth -= lines[i].count("</div>")
                i += 1
                if started and depth == 0:
                    break
            continue

        # Remove users tab from array
        if "{ id: 'users'" in line:
            i += 1
            continue

        # Remove user-related state variables
        if "const users = ref([])" in line or \
           "const showUserModal = ref(false)" in line or \
           "const isEditMode = ref(false)" in line or \
           ("const userForm = ref({" in line and "user_id" in line):
            i += 1
            continue

        # Skip loadUsers function
        if "async function loadUsers()" in line:
            depth = 0
            started = False
            while i < len(lines):
                if "{" in lines[i]:
                    depth += lines[i].count("{")
                    started = True
                if "}" in lines[i]:
                    depth -= lines[i].count("}")
                i += 1
                if started and depth == 0:
                    break
            continue

        # Skip user modal functions
        if "function openAddUserModal()" in line or \
           "function openEditUserModal(user)" in line or \
           "function closeUserModal()" in line:
            depth = 0
            started = False
            while i < len(lines):
                if "{" in lines[i]:
                    depth += lines[i].count("{")
                    started = True
                if "}" in lines[i]:
                    depth -= lines[i].count("}")
                i += 1
                if started and depth == 0:
                    break
            continue

        # Skip saveUser function
        if "async function saveUser()" in line:
            depth = 0
            started = False
            while i < len(lines):
                if "{" in lines[i]:
                    depth += lines[i].count("{")
                    started = True
                if "}" in lines[i]:
                    depth -= lines[i].count("}")
                i += 1
                if started and depth == 0:
                    break
            continue

        # Skip toggleUserStatus function
        if "async function toggleUserStatus(user)" in line:
            depth = 0
            started = False
            while i < len(lines):
                if "{" in lines[i]:
                    depth += lines[i].count("{")
                    started = True
                if "}" in lines[i]:
                    depth -= lines[i].count("}")
                i += 1
                if started and depth == 0:
                    break
            continue

        # Skip deleteUser function
        if "async function deleteUser(userId)" in line:
            depth = 0
            started = False
            while i < len(lines):
                if "{" in lines[i]:
                    depth += lines[i].count("{")
                    started = True
                if "}" in lines[i]:
                    depth -= lines[i].count("}")
                i += 1
                if started and depth == 0:
                    break
            continue

        # Remove loadUsers call from onMounted
        if "await loadUsers()" in line:
            i += 1
            continue

        # Keep this line
        new_lines.append(line)
        i += 1

    # Update default activeTab to 'version' instead of 'users'
    for i, line in enumerate(new_lines):
        if "const activeTab = ref('users')" in line:
            new_lines[i] = line.replace("'users'", "'version'")

    # Write back
    with open(file_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

    print(f"User management cleaned successfully")
    print(f"Removed {len(lines) - len(new_lines)} lines")

if __name__ == "__main__":
    clean_user_management()
