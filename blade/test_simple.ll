; ModuleID = "saw_module"
target triple = "arm64-apple-darwin24.5.0"
target datalayout = ""

%"Range" = type {i64, i64}
%"DataBuffer" = type {i8*, i64, i64}
%"Data" = type {{i1, %"DataBuffer"*}, i64, i64}
%"DataIterator" = type {{i1, %"DataBuffer"*}, i64, i64, i64}
%"Directory" = type {i64}
%"Env" = type {i64}
%"File" = type {i32}
%"Path" = type {i8*}
%"CommandOutput" = type {i8*, i32}
%"Command" = type {i8*, {i1, i8*}, i64, i64}
%"StringBuilder" = type {{i1, i8*}, i64, i64}
%"Vector_Path" = type {{i1, %"Path"*}, i64, i64}
%"VectorIterator_Path" = type {{i1, %"Path"*}, i64, i64}
%"Vector_String" = type {{i1, i8**}, i64, i64}
%"VectorIterator_String" = type {{i1, i8**}, i64, i64}
declare i32 @"printf"(i8* %".1", ...)

declare void @"abort"()

declare i32 @"snprintf"(i8* %".1", i64 %".2", i8* %".3", ...)

declare i8* @"strcpy"(i8* %".1", i8* %".2")

declare i8* @"strcat"(i8* %".1", i8* %".2")

declare external i8* @"malloc"(i64 %".1")

declare external i8* @"realloc"(i8* %".1", i64 %".2")

declare external void @"free"(i8* %".1")

declare external i8* @"memcpy"(i8* %".1", i8* %".2", i64 %".3")

declare external i8* @"opendir"(i8* %".1")

declare external i8* @"readdir"(i8* %".1")

declare external i32 @"closedir"(i8* %".1")

declare external i32 @"mkdir"(i8* %".1", i64 %".2")

declare external i32 @"rmdir"(i8* %".1")

declare external i32 @"chdir"(i8* %".1")

declare external i8* @"getcwd"(i8* %".1", i64 %".2")

declare external i8* @"getenv"(i8* %".1")

declare external i32 @"setenv"(i8* %".1", i8* %".2", i32 %".3")

declare external i32 @"unsetenv"(i8* %".1")

declare external i8* @"_NSGetArgc"()

declare external i8* @"_NSGetArgv"()

declare external i32 @"open"(i8* %".1", i32 %".2", ...)

declare external i64 @"read"(i32 %".1", i8* %".2", i64 %".3")

declare external i64 @"write"(i32 %".1", i8* %".2", i64 %".3")

declare external i32 @"close"(i32 %".1")

declare external i64 @"lseek"(i32 %".1", i64 %".2", i32 %".3")

declare external i32 @"access"(i8* %".1", i32 %".2")

declare external i32 @"unlink"(i8* %".1")

declare external i32 @"rename"(i8* %".1", i8* %".2")

declare external i32 @"system"(i8* %".1")

declare external i8* @"popen"(i8* %".1", i8* %".2")

declare external i32 @"pclose"(i8* %".1")

declare external i64 @"fread"(i8* %".1", i64 %".2", i64 %".3", i8* %".4")

declare external i32 @"feof"(i8* %".1")

declare external i64 @"strlen"(i8* %".1")

declare external i64 @"strlcpy"(i8* %".1", i8* %".2", i64 %".3")

declare external i64 @"strlcat"(i8* %".1", i8* %".2", i64 %".3")

define i32 @"main"()
{
entry:
  %".2" = getelementptr inbounds [18 x i8], [18 x i8]* @".str.0", i32 0, i32 0
  %".3" = getelementptr inbounds [4 x i8], [4 x i8]* @".str.1", i32 0, i32 0
  %".4" = call i32 (i8*, ...) @"printf"(i8* %".3", i8* %".2")
  ret i32 0
}

define {i1, i64} @"Range_next"(%"Range"* %"self")
{
entry:
  %"if_result" = alloca {i1, i64}
  %"self.1" = load %"Range", %"Range"* %"self"
  %".3" = extractvalue %"Range" %"self.1", 0
  %"self.2" = load %"Range", %"Range"* %"self"
  %".4" = extractvalue %"Range" %"self.2", 1
  %"lttmp" = icmp slt i64 %".3", %".4"
  br i1 %"lttmp", label %"then", label %"else"
then:
  %"self.3" = load %"Range", %"Range"* %"self"
  %".6" = extractvalue %"Range" %"self.3", 0
  %"result" = alloca i64
  store i64 %".6", i64* %"result"
  %"self.4" = load %"Range", %"Range"* %"self"
  %".8" = extractvalue %"Range" %"self.4", 0
  %"addtmp" = add i64 %".8", 1
  %"current_ptr" = getelementptr %"Range", %"Range"* %"self", i32 0, i32 0
  store i64 %"addtmp", i64* %"current_ptr"
  %"result.1" = load i64, i64* %"result"
  %".11" = insertvalue {i1, i64} undef, i1 1, 0
  %"some_then" = insertvalue {i1, i64} %".11", i64 %"result.1", 1
  store {i1, i64} %"some_then", {i1, i64}* %"if_result"
  br label %"ifcont"
else:
  %".10" = insertvalue {i1, i64} undef, i1 0, 0
  store {i1, i64} %".10", {i1, i64}* %"if_result"
  br label %"ifcont"
ifcont:
  %"iftmp" = load {i1, i64}, {i1, i64}* %"if_result"
  ret {i1, i64} %"iftmp"
}

define %"Data" @"Data_init_"()
{
entry:
  %".2" = insertvalue {i1, %"DataBuffer"*} undef, i1 0, 0
  %".3" = insertvalue %"Data" undef, {i1, %"DataBuffer"*} %".2", 0
  %".4" = insertvalue %"Data" %".3", i64 0, 1
  %".5" = insertvalue %"Data" %".4", i64 0, 2
  ret %"Data" %".5"
}

define %"Data" @"Data_init_capacity"(i64 %"capacity")
{
entry:
  %"capacity.1" = alloca i64
  store i64 %"capacity", i64* %"capacity.1"
  %".4" = insertvalue {i1, %"DataBuffer"*} undef, i1 0, 0
  %".5" = insertvalue %"Data" undef, {i1, %"DataBuffer"*} %".4", 0
  %".6" = insertvalue %"Data" %".5", i64 0, 1
  %".7" = insertvalue %"Data" %".6", i64 0, 2
  %"data" = alloca %"Data"
  store %"Data" %".7", %"Data"* %"data"
  %"data.1" = load %"Data", %"Data"* %"data"
  %"capacity.2" = load i64, i64* %"capacity.1"
  call void @"Data_ensure_capacity"(%"Data"* %"data", i64 %"capacity.2")
  %"data_moved" = load %"Data", %"Data"* %"data"
  ret %"Data" %"data_moved"
}

define i64 @"Data_len"(%"Data" %"self")
{
entry:
  %"self.1" = alloca %"Data"
  store %"Data" %"self", %"Data"* %"self.1"
  %"self.2" = load %"Data", %"Data"* %"self.1"
  %".4" = extractvalue %"Data" %"self.2", 2
  ret i64 %".4"
}

define i1 @"Data_is_empty"(%"Data" %"self")
{
entry:
  %"self.1" = alloca %"Data"
  store %"Data" %"self", %"Data"* %"self.1"
  %"self.2" = load %"Data", %"Data"* %"self.1"
  %".4" = extractvalue %"Data" %"self.2", 2
  %"eqtmp" = icmp eq i64 %".4", 0
  ret i1 %"eqtmp"
}

define i64 @"Data_capacity"(%"Data" %"self")
{
entry:
  %"if_let_result" = alloca i64
  %"self.1" = alloca %"Data"
  store %"Data" %"self", %"Data"* %"self.1"
  %"self.2" = load %"Data", %"Data"* %"self.1"
  %".4" = extractvalue %"Data" %"self.2", 0
  %"is_some" = extractvalue {i1, %"DataBuffer"*} %".4", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, %"DataBuffer"*} %".4", 1
  %"inner" = alloca %"DataBuffer"*
  store %"DataBuffer"* %"unwrapped", %"DataBuffer"** %"inner"
  %"inner.1" = load %"DataBuffer"*, %"DataBuffer"** %"inner"
  %"ptr_idx" = getelementptr %"DataBuffer", %"DataBuffer"* %"inner.1", i64 0
  %"ptr_elem" = load %"DataBuffer", %"DataBuffer"* %"ptr_idx"
  %".7" = extractvalue %"DataBuffer" %"ptr_elem", 1
  store i64 %".7", i64* %"if_let_result"
  br label %"if_let_merge"
if_let_else:
  store i64 0, i64* %"if_let_result"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp" = load i64, i64* %"if_let_result"
  ret i64 %"if_let_tmp"
}

define {i1, i8} @"Data_get"(%"Data" %"self", i64 %"index")
{
entry:
  %"self.1" = alloca %"Data"
  store %"Data" %"self", %"Data"* %"self.1"
  %"index.1" = alloca i64
  store i64 %"index", i64* %"index.1"
  %"index.2" = load i64, i64* %"index.1"
  %"lttmp" = icmp slt i64 %"index.2", 0
  br i1 %"lttmp", label %"or_merge", label %"or_right"
or_right:
  %"index.3" = load i64, i64* %"index.1"
  %"self.2" = load %"Data", %"Data"* %"self.1"
  %".7" = extractvalue %"Data" %"self.2", 2
  %"getmp" = icmp sge i64 %"index.3", %".7"
  br label %"or_merge"
or_merge:
  %"or_result" = phi  i1 [1, %"entry"], [%"getmp", %"or_right"]
  br i1 %"or_result", label %"then", label %"else"
then:
  %".10" = insertvalue {i1, i8} undef, i1 0, 0
  ret {i1, i8} %".10"
else:
  br label %"ifcont"
ifcont:
  %"self.3" = load %"Data", %"Data"* %"self.1"
  %".13" = extractvalue %"Data" %"self.3", 0
  %"guard_is_some" = extractvalue {i1, %"DataBuffer"*} %".13", 0
  br i1 %"guard_is_some", label %"guard_continue", label %"guard_else"
guard_else:
  %".15" = insertvalue {i1, i8} undef, i1 0, 0
  ret {i1, i8} %".15"
guard_continue:
  %"guard_unwrapped" = extractvalue {i1, %"DataBuffer"*} %".13", 1
  %"inner" = alloca %"DataBuffer"*
  store %"DataBuffer"* %"guard_unwrapped", %"DataBuffer"** %"inner"
  %"inner.1" = load %"DataBuffer"*, %"DataBuffer"** %"inner"
  %"ptr_idx" = getelementptr %"DataBuffer", %"DataBuffer"* %"inner.1", i64 0
  %"ptr_elem" = load %"DataBuffer", %"DataBuffer"* %"ptr_idx"
  %".18" = extractvalue %"DataBuffer" %"ptr_elem", 0
  %"buf" = alloca i8*
  store i8* %".18", i8** %"buf"
  %"buf.1" = load i8*, i8** %"buf"
  %"self.4" = load %"Data", %"Data"* %"self.1"
  %".20" = extractvalue %"Data" %"self.4", 1
  %"index.4" = load i64, i64* %"index.1"
  %"addtmp" = add i64 %".20", %"index.4"
  %"ptr_idx.1" = getelementptr i8, i8* %"buf.1", i64 %"addtmp"
  %"ptr_elem.1" = load i8, i8* %"ptr_idx.1"
  %".21" = insertvalue {i1, i8} undef, i1 1, 0
  %".22" = insertvalue {i1, i8} %".21", i8 %"ptr_elem.1", 1
  ret {i1, i8} %".22"
}

define i1 @"Data_set"(%"Data"* %"self", i64 %"index", i8 %"value")
{
entry:
  %"index.1" = alloca i64
  store i64 %"index", i64* %"index.1"
  %"value.1" = alloca i8
  store i8 %"value", i8* %"value.1"
  %"index.2" = load i64, i64* %"index.1"
  %"lttmp" = icmp slt i64 %"index.2", 0
  br i1 %"lttmp", label %"or_merge", label %"or_right"
or_right:
  %"index.3" = load i64, i64* %"index.1"
  %"self.1" = load %"Data", %"Data"* %"self"
  %".8" = extractvalue %"Data" %"self.1", 2
  %"getmp" = icmp sge i64 %"index.3", %".8"
  br label %"or_merge"
or_merge:
  %"or_result" = phi  i1 [1, %"entry"], [%"getmp", %"or_right"]
  br i1 %"or_result", label %"then", label %"else"
then:
  ret i1 0
else:
  br label %"ifcont"
ifcont:
  %"self.2" = load %"Data", %"Data"* %"self"
  %".13" = extractvalue %"Data" %"self.2", 0
  %"guard_is_some" = extractvalue {i1, %"DataBuffer"*} %".13", 0
  br i1 %"guard_is_some", label %"guard_continue", label %"guard_else"
guard_else:
  ret i1 0
guard_continue:
  %"guard_unwrapped" = extractvalue {i1, %"DataBuffer"*} %".13", 1
  %"inner" = alloca %"DataBuffer"*
  store %"DataBuffer"* %"guard_unwrapped", %"DataBuffer"** %"inner"
  %"inner.1" = load %"DataBuffer"*, %"DataBuffer"** %"inner"
  %"ptr_idx" = getelementptr %"DataBuffer", %"DataBuffer"* %"inner.1", i64 0
  %"ptr_elem" = load %"DataBuffer", %"DataBuffer"* %"ptr_idx"
  %".17" = extractvalue %"DataBuffer" %"ptr_elem", 0
  %"buf" = alloca i8*
  store i8* %".17", i8** %"buf"
  %"value.2" = load i8, i8* %"value.1"
  %"self.3" = load %"Data", %"Data"* %"self"
  %".19" = extractvalue %"Data" %"self.3", 1
  %"index.4" = load i64, i64* %"index.1"
  %"addtmp" = add i64 %".19", %"index.4"
  %"container" = load i8*, i8** %"buf"
  %"ptr_elem.1" = getelementptr i8, i8* %"container", i64 %"addtmp"
  store i8 %"value.2", i8* %"ptr_elem.1"
  ret i1 1
}

define void @"Data_push"(%"Data"* %"self", i8 %"value")
{
entry:
  %"value.1" = alloca i8
  store i8 %"value", i8* %"value.1"
  %"self.1" = load %"Data", %"Data"* %"self"
  %"self.2" = load %"Data", %"Data"* %"self"
  %".5" = extractvalue %"Data" %"self.2", 2
  %"addtmp" = add i64 %".5", 1
  call void @"Data_ensure_unique_capacity"(%"Data"* %"self", i64 %"addtmp")
  %"self.3" = load %"Data", %"Data"* %"self"
  %".6" = extractvalue %"Data" %"self.3", 0
  %"is_some" = extractvalue {i1, %"DataBuffer"*} %".6", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, %"DataBuffer"*} %".6", 1
  %"inner" = alloca %"DataBuffer"*
  store %"DataBuffer"* %"unwrapped", %"DataBuffer"** %"inner"
  %"inner.1" = load %"DataBuffer"*, %"DataBuffer"** %"inner"
  %"ptr_idx" = getelementptr %"DataBuffer", %"DataBuffer"* %"inner.1", i64 0
  %"ptr_elem" = load %"DataBuffer", %"DataBuffer"* %"ptr_idx"
  %".9" = extractvalue %"DataBuffer" %"ptr_elem", 0
  %"buf" = alloca i8*
  store i8* %".9", i8** %"buf"
  %"value.2" = load i8, i8* %"value.1"
  %"self.4" = load %"Data", %"Data"* %"self"
  %".11" = extractvalue %"Data" %"self.4", 1
  %"self.5" = load %"Data", %"Data"* %"self"
  %".12" = extractvalue %"Data" %"self.5", 2
  %"addtmp.1" = add i64 %".11", %".12"
  %"container" = load i8*, i8** %"buf"
  %"ptr_elem.1" = getelementptr i8, i8* %"container", i64 %"addtmp.1"
  store i8 %"value.2", i8* %"ptr_elem.1"
  %"self.6" = load %"Data", %"Data"* %"self"
  %".14" = extractvalue %"Data" %"self.6", 2
  %"addtmp.2" = add i64 %".14", 1
  %"length_ptr" = getelementptr %"Data", %"Data"* %"self", i32 0, i32 2
  store i64 %"addtmp.2", i64* %"length_ptr"
  br label %"if_let_merge"
if_let_else:
  br label %"if_let_merge"
if_let_merge:
  ret void
}

define {i1, i8} @"Data_pop"(%"Data"* %"self")
{
entry:
  %"self.1" = load %"Data", %"Data"* %"self"
  %".3" = extractvalue %"Data" %"self.1", 2
  %"eqtmp" = icmp eq i64 %".3", 0
  br i1 %"eqtmp", label %"then", label %"else"
then:
  %".5" = insertvalue {i1, i8} undef, i1 0, 0
  ret {i1, i8} %".5"
else:
  br label %"ifcont"
ifcont:
  %"self.2" = load %"Data", %"Data"* %"self"
  %".8" = extractvalue %"Data" %"self.2", 0
  %"guard_is_some" = extractvalue {i1, %"DataBuffer"*} %".8", 0
  br i1 %"guard_is_some", label %"guard_continue", label %"guard_else"
guard_else:
  %".10" = insertvalue {i1, i8} undef, i1 0, 0
  ret {i1, i8} %".10"
guard_continue:
  %"guard_unwrapped" = extractvalue {i1, %"DataBuffer"*} %".8", 1
  %"inner" = alloca %"DataBuffer"*
  store %"DataBuffer"* %"guard_unwrapped", %"DataBuffer"** %"inner"
  %"inner.1" = load %"DataBuffer"*, %"DataBuffer"** %"inner"
  %"ptr_idx" = getelementptr %"DataBuffer", %"DataBuffer"* %"inner.1", i64 0
  %"ptr_elem" = load %"DataBuffer", %"DataBuffer"* %"ptr_idx"
  %".13" = extractvalue %"DataBuffer" %"ptr_elem", 0
  %"buf" = alloca i8*
  store i8* %".13", i8** %"buf"
  %"buf.1" = load i8*, i8** %"buf"
  %"self.3" = load %"Data", %"Data"* %"self"
  %".15" = extractvalue %"Data" %"self.3", 1
  %"self.4" = load %"Data", %"Data"* %"self"
  %".16" = extractvalue %"Data" %"self.4", 2
  %"addtmp" = add i64 %".15", %".16"
  %"subtmp" = sub i64 %"addtmp", 1
  %"ptr_idx.1" = getelementptr i8, i8* %"buf.1", i64 %"subtmp"
  %"ptr_elem.1" = load i8, i8* %"ptr_idx.1"
  %"value" = alloca i8
  store i8 %"ptr_elem.1", i8* %"value"
  %"self.5" = load %"Data", %"Data"* %"self"
  %".18" = extractvalue %"Data" %"self.5", 2
  %"subtmp.1" = sub i64 %".18", 1
  %"length_ptr" = getelementptr %"Data", %"Data"* %"self", i32 0, i32 2
  store i64 %"subtmp.1", i64* %"length_ptr"
  %"value.1" = load i8, i8* %"value"
  %".20" = insertvalue {i1, i8} undef, i1 1, 0
  %".21" = insertvalue {i1, i8} %".20", i8 %"value.1", 1
  ret {i1, i8} %".21"
}

define void @"Data_clear"(%"Data"* %"self")
{
entry:
  %"length_ptr" = getelementptr %"Data", %"Data"* %"self", i32 0, i32 2
  store i64 0, i64* %"length_ptr"
  ret void
}

define void @"Data_append"(%"Data"* %"self", %"Data" %"other")
{
entry:
  %"other.1" = alloca %"Data"
  store %"Data" %"other", %"Data"* %"other.1"
  %"other.2" = load %"Data", %"Data"* %"other.1"
  %".5" = extractvalue %"Data" %"other.2", 2
  %"eqtmp" = icmp eq i64 %".5", 0
  br i1 %"eqtmp", label %"then", label %"else"
then:
  ret void
else:
  br label %"ifcont"
ifcont:
  %"self.1" = load %"Data", %"Data"* %"self"
  %"self.2" = load %"Data", %"Data"* %"self"
  %".9" = extractvalue %"Data" %"self.2", 2
  %"other.3" = load %"Data", %"Data"* %"other.1"
  %".10" = extractvalue %"Data" %"other.3", 2
  %"addtmp" = add i64 %".9", %".10"
  call void @"Data_ensure_unique_capacity"(%"Data"* %"self", i64 %"addtmp")
  %"self.3" = load %"Data", %"Data"* %"self"
  %".11" = extractvalue %"Data" %"self.3", 0
  %"is_some" = extractvalue {i1, %"DataBuffer"*} %".11", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, %"DataBuffer"*} %".11", 1
  %"self_inner" = alloca %"DataBuffer"*
  store %"DataBuffer"* %"unwrapped", %"DataBuffer"** %"self_inner"
  %"other.4" = load %"Data", %"Data"* %"other.1"
  %".14" = extractvalue %"Data" %"other.4", 0
  %"is_some.1" = extractvalue {i1, %"DataBuffer"*} %".14", 0
  br i1 %"is_some.1", label %"if_let_then.1", label %"if_let_else.1"
if_let_else:
  br label %"if_let_merge"
if_let_merge:
  ret void
if_let_then.1:
  %"unwrapped.1" = extractvalue {i1, %"DataBuffer"*} %".14", 1
  %"other_inner" = alloca %"DataBuffer"*
  store %"DataBuffer"* %"unwrapped.1", %"DataBuffer"** %"other_inner"
  %"self_inner.1" = load %"DataBuffer"*, %"DataBuffer"** %"self_inner"
  %"ptr_idx" = getelementptr %"DataBuffer", %"DataBuffer"* %"self_inner.1", i64 0
  %"ptr_elem" = load %"DataBuffer", %"DataBuffer"* %"ptr_idx"
  %".17" = extractvalue %"DataBuffer" %"ptr_elem", 0
  %"dest" = alloca i8*
  store i8* %".17", i8** %"dest"
  %"other_inner.1" = load %"DataBuffer"*, %"DataBuffer"** %"other_inner"
  %"ptr_idx.1" = getelementptr %"DataBuffer", %"DataBuffer"* %"other_inner.1", i64 0
  %"ptr_elem.1" = load %"DataBuffer", %"DataBuffer"* %"ptr_idx.1"
  %".19" = extractvalue %"DataBuffer" %"ptr_elem.1", 0
  %"src" = alloca i8*
  store i8* %".19", i8** %"src"
  %"dest.1" = load i8*, i8** %"dest"
  %"self.4" = load %"Data", %"Data"* %"self"
  %".21" = extractvalue %"Data" %"self.4", 1
  %"ptr_add" = getelementptr i8, i8* %"dest.1", i64 %".21"
  %"self.5" = load %"Data", %"Data"* %"self"
  %".22" = extractvalue %"Data" %"self.5", 2
  %"ptr_add.1" = getelementptr i8, i8* %"ptr_add", i64 %".22"
  %"dest_offset" = alloca i8*
  store i8* %"ptr_add.1", i8** %"dest_offset"
  %"src.1" = load i8*, i8** %"src"
  %"other.5" = load %"Data", %"Data"* %"other.1"
  %".24" = extractvalue %"Data" %"other.5", 1
  %"ptr_add.2" = getelementptr i8, i8* %"src.1", i64 %".24"
  %"src_offset" = alloca i8*
  store i8* %"ptr_add.2", i8** %"src_offset"
  %"dest_offset.1" = load i8*, i8** %"dest_offset"
  %"src_offset.1" = load i8*, i8** %"src_offset"
  %"other.6" = load %"Data", %"Data"* %"other.1"
  %".26" = extractvalue %"Data" %"other.6", 2
  %"calltmp" = call i8* @"memcpy"(i8* %"dest_offset.1", i8* %"src_offset.1", i64 %".26")
  %"self.6" = load %"Data", %"Data"* %"self"
  %".27" = extractvalue %"Data" %"self.6", 2
  %"other.7" = load %"Data", %"Data"* %"other.1"
  %".28" = extractvalue %"Data" %"other.7", 2
  %"addtmp.1" = add i64 %".27", %".28"
  %"length_ptr" = getelementptr %"Data", %"Data"* %"self", i32 0, i32 2
  store i64 %"addtmp.1", i64* %"length_ptr"
  br label %"if_let_merge.1"
if_let_else.1:
  br label %"if_let_merge.1"
if_let_merge.1:
  br label %"if_let_merge"
}

define {i1, %"Data"} @"Data_slice"(%"Data"* %"self", i64 %"start", i64 %"end")
{
entry:
  %"start.1" = alloca i64
  store i64 %"start", i64* %"start.1"
  %"end.1" = alloca i64
  store i64 %"end", i64* %"end.1"
  %"start.2" = load i64, i64* %"start.1"
  %"lttmp" = icmp slt i64 %"start.2", 0
  br i1 %"lttmp", label %"or_merge.1", label %"or_right.1"
or_right:
  %"end.3" = load i64, i64* %"end.1"
  %"self.1" = load %"Data", %"Data"* %"self"
  %".10" = extractvalue %"Data" %"self.1", 2
  %"gttmp" = icmp sgt i64 %"end.3", %".10"
  br label %"or_merge"
or_merge:
  %"or_result.1" = phi  i1 [1, %"or_merge.1"], [%"gttmp", %"or_right"]
  br i1 %"or_result.1", label %"then", label %"else"
or_right.1:
  %"end.2" = load i64, i64* %"end.1"
  %"start.3" = load i64, i64* %"start.1"
  %"lttmp.1" = icmp slt i64 %"end.2", %"start.3"
  br label %"or_merge.1"
or_merge.1:
  %"or_result" = phi  i1 [1, %"entry"], [%"lttmp.1", %"or_right.1"]
  br i1 %"or_result", label %"or_merge", label %"or_right"
then:
  %".13" = insertvalue {i1, %"Data"} undef, i1 0, 0
  ret {i1, %"Data"} %".13"
else:
  br label %"ifcont"
ifcont:
  %"self.2" = load %"Data", %"Data"* %"self"
  %".16" = extractvalue %"Data" %"self.2", 2
  %"eqtmp" = icmp eq i64 %".16", 0
  br i1 %"eqtmp", label %"then.1", label %"else.1"
then.1:
  %"start.4" = load i64, i64* %"start.1"
  %"eqtmp.1" = icmp eq i64 %"start.4", 0
  br i1 %"eqtmp.1", label %"and_right", label %"and_merge"
else.1:
  br label %"ifcont.1"
ifcont.1:
  %"self.3" = load %"Data", %"Data"* %"self"
  %".28" = extractvalue %"Data" %"self.3", 0
  %"guard_is_some" = extractvalue {i1, %"DataBuffer"*} %".28", 0
  br i1 %"guard_is_some", label %"guard_continue", label %"guard_else"
and_right:
  %"end.4" = load i64, i64* %"end.1"
  %"eqtmp.2" = icmp eq i64 %"end.4", 0
  br label %"and_merge"
and_merge:
  %"and_result" = phi  i1 [0, %"then.1"], [%"eqtmp.2", %"and_right"]
  br i1 %"and_result", label %"then.2", label %"else.2"
then.2:
  %".21" = insertvalue {i1, %"Data"} undef, i1 1, 0
  %".22" = insertvalue {i1, %"Data"} %".21", %"Data" undef, 1
  ret {i1, %"Data"} %".22"
else.2:
  br label %"ifcont.2"
ifcont.2:
  %".25" = insertvalue {i1, %"Data"} undef, i1 0, 0
  ret {i1, %"Data"} %".25"
guard_else:
  %".30" = insertvalue {i1, %"Data"} undef, i1 0, 0
  ret {i1, %"Data"} %".30"
guard_continue:
  %"guard_unwrapped" = extractvalue {i1, %"DataBuffer"*} %".28", 1
  %"inner" = alloca %"DataBuffer"*
  store %"DataBuffer"* %"guard_unwrapped", %"DataBuffer"** %"inner"
  %"inner.1" = load %"DataBuffer"*, %"DataBuffer"** %"inner"
  %"ptr_idx" = getelementptr %"DataBuffer", %"DataBuffer"* %"inner.1", i64 0
  %"ptr_elem" = load %"DataBuffer", %"DataBuffer"* %"ptr_idx"
  %".33" = extractvalue %"DataBuffer" %"ptr_elem", 2
  %"addtmp" = add i64 %".33", 1
  %"inner.2" = load %"DataBuffer"*, %"DataBuffer"** %"inner"
  %"ptr_idx.1" = getelementptr %"DataBuffer", %"DataBuffer"* %"inner.2", i64 0
  %"refcount_ptr" = getelementptr %"DataBuffer", %"DataBuffer"* %"ptr_idx.1", i32 0, i32 2
  store i64 %"addtmp", i64* %"refcount_ptr"
  %"self.4" = load %"Data", %"Data"* %"self"
  %".35" = extractvalue %"Data" %"self.4", 0
  %"self.5" = load %"Data", %"Data"* %"self"
  %".36" = extractvalue %"Data" %"self.5", 1
  %"start.5" = load i64, i64* %"start.1"
  %"addtmp.1" = add i64 %".36", %"start.5"
  %"end.5" = load i64, i64* %"end.1"
  %"start.6" = load i64, i64* %"start.1"
  %"subtmp" = sub i64 %"end.5", %"start.6"
  %".37" = insertvalue %"Data" undef, {i1, %"DataBuffer"*} %".35", 0
  %".38" = insertvalue %"Data" %".37", i64 %"addtmp.1", 1
  %".39" = insertvalue %"Data" %".38", i64 %"subtmp", 2
  %".40" = insertvalue {i1, %"Data"} undef, i1 1, 0
  %".41" = insertvalue {i1, %"Data"} %".40", %"Data" %".39", 1
  ret {i1, %"Data"} %".41"
}

define %"Data" @"Data_copy"(%"Data" %"self")
{
entry:
  %"self.1" = alloca %"Data"
  store %"Data" %"self", %"Data"* %"self.1"
  %"self.2" = load %"Data", %"Data"* %"self.1"
  %".4" = extractvalue %"Data" %"self.2", 2
  %"eqtmp" = icmp eq i64 %".4", 0
  br i1 %"eqtmp", label %"then", label %"else"
then:
  ret %"Data" undef
else:
  br label %"ifcont"
ifcont:
  %".8" = call %"Data" @"Data_init_"()
  %"new_data" = alloca %"Data"
  store %"Data" %".8", %"Data"* %"new_data"
  %"new_data.1" = load %"Data", %"Data"* %"new_data"
  %"self.3" = load %"Data", %"Data"* %"self.1"
  %".10" = extractvalue %"Data" %"self.3", 2
  call void @"Data_ensure_capacity"(%"Data"* %"new_data", i64 %".10")
  %"self.4" = load %"Data", %"Data"* %"self.1"
  %".11" = extractvalue %"Data" %"self.4", 2
  %"length_ptr" = getelementptr %"Data", %"Data"* %"new_data", i32 0, i32 2
  store i64 %".11", i64* %"length_ptr"
  %"i" = alloca i64
  store i64 0, i64* %"i"
  br label %"while.cond"
while.cond:
  %"i.1" = load i64, i64* %"i"
  %"self.5" = load %"Data", %"Data"* %"self.1"
  %".15" = extractvalue %"Data" %"self.5", 2
  %"lttmp" = icmp slt i64 %"i.1", %".15"
  br i1 %"lttmp", label %"while.body", label %"while.end"
while.body:
  %"self.6" = load %"Data", %"Data"* %"self.1"
  %"i.2" = load i64, i64* %"i"
  %"methodcall.1" = call {i1, i8} @"Data_get"(%"Data" %"self.6", i64 %"i.2")
  %"is_some" = extractvalue {i1, i8} %"methodcall.1", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
while.end:
  %"new_data_moved" = load %"Data", %"Data"* %"new_data"
  ret %"Data" %"new_data_moved"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8} %"methodcall.1", 1
  %"b" = alloca i8
  store i8 %"unwrapped", i8* %"b"
  %"new_data.2" = load %"Data", %"Data"* %"new_data"
  %"i.3" = load i64, i64* %"i"
  %"b.1" = load i8, i8* %"b"
  %"methodcall.2" = call i1 @"Data_set"(%"Data"* %"new_data", i64 %"i.3", i8 %"b.1")
  br label %"if_let_merge"
if_let_else:
  br label %"if_let_merge"
if_let_merge:
  %"i.4" = load i64, i64* %"i"
  %"addtmp" = add i64 %"i.4", 1
  store i64 %"addtmp", i64* %"i"
  br label %"while.cond"
}

define %"DataIterator" @"Data_iter"(%"Data" %"self")
{
entry:
  %"self.1" = alloca %"Data"
  store %"Data" %"self", %"Data"* %"self.1"
  %"self.2" = load %"Data", %"Data"* %"self.1"
  %".4" = extractvalue %"Data" %"self.2", 0
  %"self.3" = load %"Data", %"Data"* %"self.1"
  %".5" = extractvalue %"Data" %"self.3", 1
  %"self.4" = load %"Data", %"Data"* %"self.1"
  %".6" = extractvalue %"Data" %"self.4", 2
  %".7" = insertvalue %"DataIterator" undef, {i1, %"DataBuffer"*} %".4", 0
  %".8" = insertvalue %"DataIterator" %".7", i64 %".5", 1
  %".9" = insertvalue %"DataIterator" %".8", i64 %".6", 2
  %".10" = insertvalue %"DataIterator" %".9", i64 0, 3
  ret %"DataIterator" %".10"
}

define i8* @"Data_to_string"(%"Data" %"self")
{
entry:
  %"self.1" = alloca %"Data"
  store %"Data" %"self", %"Data"* %"self.1"
  %".4" = call %"StringBuilder" @"StringBuilder_init_"()
  %"sb" = alloca %"StringBuilder"
  store %"StringBuilder" %".4", %"StringBuilder"* %"sb"
  %"i" = alloca i64
  store i64 0, i64* %"i"
  br label %"while.cond"
while.cond:
  %"i.1" = load i64, i64* %"i"
  %"self.2" = load %"Data", %"Data"* %"self.1"
  %".8" = extractvalue %"Data" %"self.2", 2
  %"lttmp" = icmp slt i64 %"i.1", %".8"
  br i1 %"lttmp", label %"while.body", label %"while.end"
while.body:
  %"self.3" = load %"Data", %"Data"* %"self.1"
  %"i.2" = load i64, i64* %"i"
  %"methodcall" = call {i1, i8} @"Data_get"(%"Data" %"self.3", i64 %"i.2")
  %"is_some" = extractvalue {i1, i8} %"methodcall", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
while.end:
  %"sb.2" = load %"StringBuilder", %"StringBuilder"* %"sb"
  %"methodcall.2" = call i8* @"StringBuilder_as_str"(%"StringBuilder" %"sb.2")
  call void @"StringBuilder_deinit"(%"StringBuilder"* %"sb")
  ret i8* %"methodcall.2"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8} %"methodcall", 1
  %"b" = alloca i8
  store i8 %"unwrapped", i8* %"b"
  %"sb.1" = load %"StringBuilder", %"StringBuilder"* %"sb"
  %"b.1" = load i8, i8* %"b"
  call void @"StringBuilder_append_char"(%"StringBuilder"* %"sb", i8 %"b.1")
  br label %"if_let_merge"
if_let_else:
  br label %"if_let_merge"
if_let_merge:
  %"i.3" = load i64, i64* %"i"
  %"addtmp" = add i64 %"i.3", 1
  store i64 %"addtmp", i64* %"i"
  br label %"while.cond"
}

define void @"Data_ensure_capacity"(%"Data"* %"self", i64 %"min_capacity")
{
entry:
  %"min_capacity.1" = alloca i64
  store i64 %"min_capacity", i64* %"min_capacity.1"
  %"self.1" = load %"Data", %"Data"* %"self"
  %"methodcall" = call i64 @"Data_capacity"(%"Data" %"self.1")
  %"current_cap" = alloca i64
  store i64 %"methodcall", i64* %"current_cap"
  %"current_cap.1" = load i64, i64* %"current_cap"
  %"min_capacity.2" = load i64, i64* %"min_capacity.1"
  %"getmp" = icmp sge i64 %"current_cap.1", %"min_capacity.2"
  br i1 %"getmp", label %"then", label %"else"
then:
  ret void
else:
  br label %"ifcont"
ifcont:
  %"current_cap.2" = load i64, i64* %"current_cap"
  %"eqtmp" = icmp eq i64 %"current_cap.2", 0
  br i1 %"eqtmp", label %"then.1", label %"else.1"
then.1:
  br label %"ifcont.1"
else.1:
  %"current_cap.3" = load i64, i64* %"current_cap"
  br label %"ifcont.1"
ifcont.1:
  %"iftmp" = phi  i64 [16, %"then.1"], [%"current_cap.3", %"else.1"]
  %"new_capacity" = alloca i64
  store i64 %"iftmp", i64* %"new_capacity"
  br label %"while.cond"
while.cond:
  %"new_capacity.1" = load i64, i64* %"new_capacity"
  %"min_capacity.3" = load i64, i64* %"min_capacity.1"
  %"lttmp" = icmp slt i64 %"new_capacity.1", %"min_capacity.3"
  br i1 %"lttmp", label %"while.body", label %"while.end"
while.body:
  %"new_capacity.2" = load i64, i64* %"new_capacity"
  %"multmp" = mul i64 %"new_capacity.2", 2
  store i64 %"multmp", i64* %"new_capacity"
  br label %"while.cond"
while.end:
  %"self.2" = load %"Data", %"Data"* %"self"
  %".17" = extractvalue %"Data" %"self.2", 0
  %"is_some" = extractvalue {i1, %"DataBuffer"*} %".17", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, %"DataBuffer"*} %".17", 1
  %"inner" = alloca %"DataBuffer"*
  store %"DataBuffer"* %"unwrapped", %"DataBuffer"** %"inner"
  %"inner.1" = load %"DataBuffer"*, %"DataBuffer"** %"inner"
  %"ptr_idx" = getelementptr %"DataBuffer", %"DataBuffer"* %"inner.1", i64 0
  %"ptr_elem" = load %"DataBuffer", %"DataBuffer"* %"ptr_idx"
  %".20" = extractvalue %"DataBuffer" %"ptr_elem", 0
  %"raw" = alloca i8*
  store i8* %".20", i8** %"raw"
  %"raw.1" = load i8*, i8** %"raw"
  %"new_capacity.3" = load i64, i64* %"new_capacity"
  %"calltmp" = call i8* @"realloc"(i8* %"raw.1", i64 %"new_capacity.3")
  %"is_not_null" = icmp ne i8* %"calltmp", null
  %"opt_flag" = insertvalue {i1, i8*} undef, i1 %"is_not_null", 0
  %"opt_val" = insertvalue {i1, i8*} %"opt_flag", i8* %"calltmp", 1
  %"is_some.1" = extractvalue {i1, i8*} %"opt_val", 0
  br i1 %"is_some.1", label %"if_let_then.1", label %"if_let_else.1"
if_let_else:
  %"self.3" = load %"Data", %"Data"* %"self"
  %"new_capacity.5" = load i64, i64* %"new_capacity"
  call void @"Data_allocate_buffer"(%"Data"* %"self", i64 %"new_capacity.5")
  br label %"if_let_merge"
if_let_merge:
  ret void
if_let_then.1:
  %"unwrapped.1" = extractvalue {i1, i8*} %"opt_val", 1
  %"new_raw" = alloca i8*
  store i8* %"unwrapped.1", i8** %"new_raw"
  %"new_raw.1" = load i8*, i8** %"new_raw"
  %"inner.2" = load %"DataBuffer"*, %"DataBuffer"** %"inner"
  %"ptr_idx.1" = getelementptr %"DataBuffer", %"DataBuffer"* %"inner.2", i64 0
  %"buffer_ptr" = getelementptr %"DataBuffer", %"DataBuffer"* %"ptr_idx.1", i32 0, i32 0
  store i8* %"new_raw.1", i8** %"buffer_ptr"
  %"new_capacity.4" = load i64, i64* %"new_capacity"
  %"inner.3" = load %"DataBuffer"*, %"DataBuffer"** %"inner"
  %"ptr_idx.2" = getelementptr %"DataBuffer", %"DataBuffer"* %"inner.3", i64 0
  %"capacity_ptr" = getelementptr %"DataBuffer", %"DataBuffer"* %"ptr_idx.2", i32 0, i32 1
  store i64 %"new_capacity.4", i64* %"capacity_ptr"
  br label %"if_let_merge.1"
if_let_else.1:
  br label %"if_let_merge.1"
if_let_merge.1:
  br label %"if_let_merge"
}

define void @"Data_make_unique"(%"Data"* %"self")
{
entry:
  %"self.1" = load %"Data", %"Data"* %"self"
  %".3" = extractvalue %"Data" %"self.1", 0
  %"guard_is_some" = extractvalue {i1, %"DataBuffer"*} %".3", 0
  br i1 %"guard_is_some", label %"guard_continue", label %"guard_else"
guard_else:
  ret void
guard_continue:
  %"guard_unwrapped" = extractvalue {i1, %"DataBuffer"*} %".3", 1
  %"inner" = alloca %"DataBuffer"*
  store %"DataBuffer"* %"guard_unwrapped", %"DataBuffer"** %"inner"
  %"inner.1" = load %"DataBuffer"*, %"DataBuffer"** %"inner"
  %"ptr_idx" = getelementptr %"DataBuffer", %"DataBuffer"* %"inner.1", i64 0
  %"ptr_elem" = load %"DataBuffer", %"DataBuffer"* %"ptr_idx"
  %".7" = extractvalue %"DataBuffer" %"ptr_elem", 2
  %"gttmp" = icmp sgt i64 %".7", 1
  br i1 %"gttmp", label %"then", label %"else"
then:
  %"self.2" = load %"Data", %"Data"* %"self"
  %"methodcall" = call %"Data" @"Data_copy"(%"Data" %"self.2")
  %"old_data" = alloca %"Data"
  store %"Data" %"methodcall", %"Data"* %"old_data"
  %"inner.2" = load %"DataBuffer"*, %"DataBuffer"** %"inner"
  %"ptr_idx.1" = getelementptr %"DataBuffer", %"DataBuffer"* %"inner.2", i64 0
  %"ptr_elem.1" = load %"DataBuffer", %"DataBuffer"* %"ptr_idx.1"
  %".10" = extractvalue %"DataBuffer" %"ptr_elem.1", 2
  %"subtmp" = sub i64 %".10", 1
  %"inner.3" = load %"DataBuffer"*, %"DataBuffer"** %"inner"
  %"ptr_idx.2" = getelementptr %"DataBuffer", %"DataBuffer"* %"inner.3", i64 0
  %"refcount_ptr" = getelementptr %"DataBuffer", %"DataBuffer"* %"ptr_idx.2", i32 0, i32 2
  store i64 %"subtmp", i64* %"refcount_ptr"
  %"old_data.1" = load %"Data", %"Data"* %"old_data"
  %".12" = extractvalue %"Data" %"old_data.1", 0
  %"inner_ptr" = getelementptr %"Data", %"Data"* %"self", i32 0, i32 0
  store {i1, %"DataBuffer"*} %".12", {i1, %"DataBuffer"*}* %"inner_ptr"
  %"old_data.2" = load %"Data", %"Data"* %"old_data"
  %".14" = extractvalue %"Data" %"old_data.2", 1
  %"offset_ptr" = getelementptr %"Data", %"Data"* %"self", i32 0, i32 1
  store i64 %".14", i64* %"offset_ptr"
  %"old_data.3" = load %"Data", %"Data"* %"old_data"
  %".16" = extractvalue %"Data" %"old_data.3", 2
  %"length_ptr" = getelementptr %"Data", %"Data"* %"self", i32 0, i32 2
  store i64 %".16", i64* %"length_ptr"
  %"self.3" = load %"Data", %"Data"* %"self"
  %".18" = extractvalue %"Data" %"self.3", 0
  %"is_some" = extractvalue {i1, %"DataBuffer"*} %".18", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
else:
  br label %"ifcont"
ifcont:
  ret void
if_let_then:
  %"unwrapped" = extractvalue {i1, %"DataBuffer"*} %".18", 1
  %"new_inner" = alloca %"DataBuffer"*
  store %"DataBuffer"* %"unwrapped", %"DataBuffer"** %"new_inner"
  %"new_inner.1" = load %"DataBuffer"*, %"DataBuffer"** %"new_inner"
  %"ptr_idx.3" = getelementptr %"DataBuffer", %"DataBuffer"* %"new_inner.1", i64 0
  %"ptr_elem.2" = load %"DataBuffer", %"DataBuffer"* %"ptr_idx.3"
  %".21" = extractvalue %"DataBuffer" %"ptr_elem.2", 2
  %"addtmp" = add i64 %".21", 1
  %"new_inner.2" = load %"DataBuffer"*, %"DataBuffer"** %"new_inner"
  %"ptr_idx.4" = getelementptr %"DataBuffer", %"DataBuffer"* %"new_inner.2", i64 0
  %"refcount_ptr.1" = getelementptr %"DataBuffer", %"DataBuffer"* %"ptr_idx.4", i32 0, i32 2
  store i64 %"addtmp", i64* %"refcount_ptr.1"
  br label %"if_let_merge"
if_let_else:
  br label %"if_let_merge"
if_let_merge:
  br label %"ifcont"
}

define void @"Data_ensure_unique_capacity"(%"Data"* %"self", i64 %"min_capacity")
{
entry:
  %"min_capacity.1" = alloca i64
  store i64 %"min_capacity", i64* %"min_capacity.1"
  %"self.1" = load %"Data", %"Data"* %"self"
  %".5" = extractvalue %"Data" %"self.1", 0
  %"is_some" = extractvalue {i1, %"DataBuffer"*} %".5", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, %"DataBuffer"*} %".5", 1
  %"inner" = alloca %"DataBuffer"*
  store %"DataBuffer"* %"unwrapped", %"DataBuffer"** %"inner"
  %"inner.1" = load %"DataBuffer"*, %"DataBuffer"** %"inner"
  %"ptr_idx" = getelementptr %"DataBuffer", %"DataBuffer"* %"inner.1", i64 0
  %"ptr_elem" = load %"DataBuffer", %"DataBuffer"* %"ptr_idx"
  %".8" = extractvalue %"DataBuffer" %"ptr_elem", 2
  %"gttmp" = icmp sgt i64 %".8", 1
  br i1 %"gttmp", label %"then", label %"else"
if_let_else:
  br label %"if_let_merge"
if_let_merge:
  %"self.3" = load %"Data", %"Data"* %"self"
  %"min_capacity.2" = load i64, i64* %"min_capacity.1"
  call void @"Data_ensure_capacity"(%"Data"* %"self", i64 %"min_capacity.2")
  ret void
then:
  %"self.2" = load %"Data", %"Data"* %"self"
  call void @"Data_make_unique"(%"Data"* %"self")
  br label %"ifcont"
else:
  br label %"ifcont"
ifcont:
  br label %"if_let_merge"
}

define void @"Data_allocate_buffer"(%"Data"* %"self", i64 %"capacity")
{
entry:
  %"capacity.1" = alloca i64
  store i64 %"capacity", i64* %"capacity.1"
  %"buffer_struct_size" = alloca i64
  store i64 24, i64* %"buffer_struct_size"
  %"buffer_struct_size.1" = load i64, i64* %"buffer_struct_size"
  %"calltmp" = call i8* @"malloc"(i64 %"buffer_struct_size.1")
  %"is_not_null" = icmp ne i8* %"calltmp", null
  %"opt_flag" = insertvalue {i1, i8*} undef, i1 %"is_not_null", 0
  %"opt_val" = insertvalue {i1, i8*} %"opt_flag", i8* %"calltmp", 1
  %"is_some" = extractvalue {i1, i8*} %"opt_val", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %"opt_val", 1
  %"inner_raw" = alloca i8*
  store i8* %"unwrapped", i8** %"inner_raw"
  %"inner_raw.1" = load i8*, i8** %"inner_raw"
  %"ptrcast" = bitcast i8* %"inner_raw.1" to %"DataBuffer"*
  %"inner" = alloca %"DataBuffer"*
  store %"DataBuffer"* %"ptrcast", %"DataBuffer"** %"inner"
  %"capacity.2" = load i64, i64* %"capacity.1"
  %"calltmp.1" = call i8* @"malloc"(i64 %"capacity.2")
  %"is_not_null.1" = icmp ne i8* %"calltmp.1", null
  %"opt_flag.1" = insertvalue {i1, i8*} undef, i1 %"is_not_null.1", 0
  %"opt_val.1" = insertvalue {i1, i8*} %"opt_flag.1", i8* %"calltmp.1", 1
  %"is_some.1" = extractvalue {i1, i8*} %"opt_val.1", 0
  br i1 %"is_some.1", label %"if_let_then.1", label %"if_let_else.1"
if_let_else:
  br label %"if_let_merge"
if_let_merge:
  ret void
if_let_then.1:
  %"unwrapped.1" = extractvalue {i1, i8*} %"opt_val.1", 1
  %"buf_raw" = alloca i8*
  store i8* %"unwrapped.1", i8** %"buf_raw"
  %"buf_raw.1" = load i8*, i8** %"buf_raw"
  %"buf" = alloca i8*
  store i8* %"buf_raw.1", i8** %"buf"
  %"buf.1" = load i8*, i8** %"buf"
  %"inner.1" = load %"DataBuffer"*, %"DataBuffer"** %"inner"
  %"ptr_idx" = getelementptr %"DataBuffer", %"DataBuffer"* %"inner.1", i64 0
  %"buffer_ptr" = getelementptr %"DataBuffer", %"DataBuffer"* %"ptr_idx", i32 0, i32 0
  store i8* %"buf.1", i8** %"buffer_ptr"
  %"capacity.3" = load i64, i64* %"capacity.1"
  %"inner.2" = load %"DataBuffer"*, %"DataBuffer"** %"inner"
  %"ptr_idx.1" = getelementptr %"DataBuffer", %"DataBuffer"* %"inner.2", i64 0
  %"capacity_ptr" = getelementptr %"DataBuffer", %"DataBuffer"* %"ptr_idx.1", i32 0, i32 1
  store i64 %"capacity.3", i64* %"capacity_ptr"
  %"inner.3" = load %"DataBuffer"*, %"DataBuffer"** %"inner"
  %"ptr_idx.2" = getelementptr %"DataBuffer", %"DataBuffer"* %"inner.3", i64 0
  %"refcount_ptr" = getelementptr %"DataBuffer", %"DataBuffer"* %"ptr_idx.2", i32 0, i32 2
  store i64 1, i64* %"refcount_ptr"
  %"inner.4" = load %"DataBuffer"*, %"DataBuffer"** %"inner"
  %"inner_ptr" = getelementptr %"Data", %"Data"* %"self", i32 0, i32 0
  %".15" = insertvalue {i1, %"DataBuffer"*} undef, i1 1, 0
  %".16" = insertvalue {i1, %"DataBuffer"*} %".15", %"DataBuffer"* %"inner.4", 1
  store {i1, %"DataBuffer"*} %".16", {i1, %"DataBuffer"*}* %"inner_ptr"
  %"offset_ptr" = getelementptr %"Data", %"Data"* %"self", i32 0, i32 1
  store i64 0, i64* %"offset_ptr"
  br label %"if_let_merge.1"
if_let_else.1:
  %"inner_raw.2" = load i8*, i8** %"inner_raw"
  call void @"free"(i8* %"inner_raw.2")
  br label %"if_let_merge.1"
if_let_merge.1:
  br label %"if_let_merge"
}

define void @"Data_deinit"(%"Data"* %"self")
{
entry:
  %"self.1" = load %"Data", %"Data"* %"self"
  %".3" = extractvalue %"Data" %"self.1", 0
  %"is_some" = extractvalue {i1, %"DataBuffer"*} %".3", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, %"DataBuffer"*} %".3", 1
  %"inner" = alloca %"DataBuffer"*
  store %"DataBuffer"* %"unwrapped", %"DataBuffer"** %"inner"
  %"inner.1" = load %"DataBuffer"*, %"DataBuffer"** %"inner"
  %"ptr_idx" = getelementptr %"DataBuffer", %"DataBuffer"* %"inner.1", i64 0
  %"ptr_elem" = load %"DataBuffer", %"DataBuffer"* %"ptr_idx"
  %".6" = extractvalue %"DataBuffer" %"ptr_elem", 2
  %"subtmp" = sub i64 %".6", 1
  %"inner.2" = load %"DataBuffer"*, %"DataBuffer"** %"inner"
  %"ptr_idx.1" = getelementptr %"DataBuffer", %"DataBuffer"* %"inner.2", i64 0
  %"refcount_ptr" = getelementptr %"DataBuffer", %"DataBuffer"* %"ptr_idx.1", i32 0, i32 2
  store i64 %"subtmp", i64* %"refcount_ptr"
  %"inner.3" = load %"DataBuffer"*, %"DataBuffer"** %"inner"
  %"ptr_idx.2" = getelementptr %"DataBuffer", %"DataBuffer"* %"inner.3", i64 0
  %"ptr_elem.1" = load %"DataBuffer", %"DataBuffer"* %"ptr_idx.2"
  %".8" = extractvalue %"DataBuffer" %"ptr_elem.1", 2
  %"eqtmp" = icmp eq i64 %".8", 0
  br i1 %"eqtmp", label %"then", label %"else"
if_let_else:
  br label %"if_let_merge"
if_let_merge:
  ret void
then:
  %"inner.4" = load %"DataBuffer"*, %"DataBuffer"** %"inner"
  %"ptr_idx.3" = getelementptr %"DataBuffer", %"DataBuffer"* %"inner.4", i64 0
  %"ptr_elem.2" = load %"DataBuffer", %"DataBuffer"* %"ptr_idx.3"
  %".10" = extractvalue %"DataBuffer" %"ptr_elem.2", 0
  %"buf" = alloca i8*
  store i8* %".10", i8** %"buf"
  %"buf.1" = load i8*, i8** %"buf"
  call void @"free"(i8* %"buf.1")
  %"inner.5" = load %"DataBuffer"*, %"DataBuffer"** %"inner"
  %"ptrcast" = bitcast %"DataBuffer"* %"inner.5" to i8*
  %"inner_raw" = alloca i8*
  store i8* %"ptrcast", i8** %"inner_raw"
  %"inner_raw.1" = load i8*, i8** %"inner_raw"
  call void @"free"(i8* %"inner_raw.1")
  br label %"ifcont"
else:
  br label %"ifcont"
ifcont:
  br label %"if_let_merge"
}

define {i1, i8} @"DataIterator_next"(%"DataIterator"* %"self")
{
entry:
  %"self.1" = load %"DataIterator", %"DataIterator"* %"self"
  %".3" = extractvalue %"DataIterator" %"self.1", 3
  %"self.2" = load %"DataIterator", %"DataIterator"* %"self"
  %".4" = extractvalue %"DataIterator" %"self.2", 2
  %"getmp" = icmp sge i64 %".3", %".4"
  br i1 %"getmp", label %"then", label %"else"
then:
  %".6" = insertvalue {i1, i8} undef, i1 0, 0
  ret {i1, i8} %".6"
else:
  br label %"ifcont"
ifcont:
  %"self.3" = load %"DataIterator", %"DataIterator"* %"self"
  %".9" = extractvalue %"DataIterator" %"self.3", 0
  %"guard_is_some" = extractvalue {i1, %"DataBuffer"*} %".9", 0
  br i1 %"guard_is_some", label %"guard_continue", label %"guard_else"
guard_else:
  %".11" = insertvalue {i1, i8} undef, i1 0, 0
  ret {i1, i8} %".11"
guard_continue:
  %"guard_unwrapped" = extractvalue {i1, %"DataBuffer"*} %".9", 1
  %"inner" = alloca %"DataBuffer"*
  store %"DataBuffer"* %"guard_unwrapped", %"DataBuffer"** %"inner"
  %"inner.1" = load %"DataBuffer"*, %"DataBuffer"** %"inner"
  %"ptr_idx" = getelementptr %"DataBuffer", %"DataBuffer"* %"inner.1", i64 0
  %"ptr_elem" = load %"DataBuffer", %"DataBuffer"* %"ptr_idx"
  %".14" = extractvalue %"DataBuffer" %"ptr_elem", 0
  %"buf" = alloca i8*
  store i8* %".14", i8** %"buf"
  %"buf.1" = load i8*, i8** %"buf"
  %"self.4" = load %"DataIterator", %"DataIterator"* %"self"
  %".16" = extractvalue %"DataIterator" %"self.4", 1
  %"self.5" = load %"DataIterator", %"DataIterator"* %"self"
  %".17" = extractvalue %"DataIterator" %"self.5", 3
  %"addtmp" = add i64 %".16", %".17"
  %"ptr_idx.1" = getelementptr i8, i8* %"buf.1", i64 %"addtmp"
  %"ptr_elem.1" = load i8, i8* %"ptr_idx.1"
  %"value" = alloca i8
  store i8 %"ptr_elem.1", i8* %"value"
  %"self.6" = load %"DataIterator", %"DataIterator"* %"self"
  %".19" = extractvalue %"DataIterator" %"self.6", 3
  %"addtmp.1" = add i64 %".19", 1
  %"index_ptr" = getelementptr %"DataIterator", %"DataIterator"* %"self", i32 0, i32 3
  store i64 %"addtmp.1", i64* %"index_ptr"
  %"value.1" = load i8, i8* %"value"
  %".21" = insertvalue {i1, i8} undef, i1 1, 0
  %".22" = insertvalue {i1, i8} %".21", i8 %"value.1", 1
  ret {i1, i8} %".22"
}

define void @"DataIterator_deinit"(%"DataIterator"* %"self")
{
entry:
  ret void
}

define {i1, %"Path"} @"Vector_Path_swap_remove"(%"Vector_Path"* %"self", i64 %"index")
{
entry:
  %"if_let_result" = alloca {i1, %"Path"}
  %"index.1" = alloca i64
  store i64 %"index", i64* %"index.1"
  %"index.2" = load i64, i64* %"index.1"
  %"lttmp" = icmp slt i64 %"index.2", 0
  br i1 %"lttmp", label %"or_merge", label %"or_right"
or_right:
  %"index.3" = load i64, i64* %"index.1"
  %"self.1" = load %"Vector_Path", %"Vector_Path"* %"self"
  %".6" = extractvalue %"Vector_Path" %"self.1", 1
  %"getmp" = icmp sge i64 %"index.3", %".6"
  br label %"or_merge"
or_merge:
  %"or_result" = phi  i1 [1, %"entry"], [%"getmp", %"or_right"]
  br i1 %"or_result", label %"then", label %"else"
then:
  %".9" = insertvalue {i1, %"Path"} undef, i1 0, 0
  br label %"ifcont"
else:
  %"self.2" = load %"Vector_Path", %"Vector_Path"* %"self"
  %".10" = extractvalue %"Vector_Path" %"self.2", 0
  %"is_some" = extractvalue {i1, %"Path"*} %".10", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
ifcont:
  %"iftmp" = phi  {i1, %"Path"} [%".9", %"then"], [%"if_let_tmp", %"if_let_merge"]
  ret {i1, %"Path"} %"iftmp"
if_let_then:
  %"unwrapped" = extractvalue {i1, %"Path"*} %".10", 1
  %"buf" = alloca %"Path"*
  store %"Path"* %"unwrapped", %"Path"** %"buf"
  %"buf.1" = load %"Path"*, %"Path"** %"buf"
  %"index.4" = load i64, i64* %"index.1"
  %"ptr_idx" = getelementptr %"Path", %"Path"* %"buf.1", i64 %"index.4"
  %"ptr_elem" = load %"Path", %"Path"* %"ptr_idx"
  %"removed" = alloca %"Path"
  store %"Path" %"ptr_elem", %"Path"* %"removed"
  %"index.5" = load i64, i64* %"index.1"
  %"self.3" = load %"Vector_Path", %"Vector_Path"* %"self"
  %".14" = extractvalue %"Vector_Path" %"self.3", 1
  %"subtmp" = sub i64 %".14", 1
  %"lttmp.1" = icmp slt i64 %"index.5", %"subtmp"
  br i1 %"lttmp.1", label %"then.1", label %"else.1"
if_let_else:
  %".22" = insertvalue {i1, %"Path"} undef, i1 0, 0
  store {i1, %"Path"} %".22", {i1, %"Path"}* %"if_let_result"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp" = load {i1, %"Path"}, {i1, %"Path"}* %"if_let_result"
  br label %"ifcont"
then.1:
  %"buf.2" = load %"Path"*, %"Path"** %"buf"
  %"self.4" = load %"Vector_Path", %"Vector_Path"* %"self"
  %".16" = extractvalue %"Vector_Path" %"self.4", 1
  %"subtmp.1" = sub i64 %".16", 1
  %"ptr_idx.1" = getelementptr %"Path", %"Path"* %"buf.2", i64 %"subtmp.1"
  %"ptr_elem.1" = load %"Path", %"Path"* %"ptr_idx.1"
  %"index.6" = load i64, i64* %"index.1"
  %"container" = load %"Path"*, %"Path"** %"buf"
  %"ptr_elem.2" = getelementptr %"Path", %"Path"* %"container", i64 %"index.6"
  store %"Path" %"ptr_elem.1", %"Path"* %"ptr_elem.2"
  br label %"ifcont.1"
else.1:
  br label %"ifcont.1"
ifcont.1:
  %"self.5" = load %"Vector_Path", %"Vector_Path"* %"self"
  %".20" = extractvalue %"Vector_Path" %"self.5", 1
  %"subtmp.2" = sub i64 %".20", 1
  %"length_ptr" = getelementptr %"Vector_Path", %"Vector_Path"* %"self", i32 0, i32 1
  store i64 %"subtmp.2", i64* %"length_ptr"
  %"removed.1" = load %"Path", %"Path"* %"removed"
  %".23" = insertvalue {i1, %"Path"} undef, i1 1, 0
  %"some_then" = insertvalue {i1, %"Path"} %".23", %"Path" %"removed.1", 1
  store {i1, %"Path"} %"some_then", {i1, %"Path"}* %"if_let_result"
  br label %"if_let_merge"
}

define %"Vector_Path" @"Vector_Path_init_"()
{
entry:
  %".2" = insertvalue {i1, %"Path"*} undef, i1 0, 0
  %".3" = insertvalue %"Vector_Path" undef, {i1, %"Path"*} %".2", 0
  %".4" = insertvalue %"Vector_Path" %".3", i64 0, 1
  %".5" = insertvalue %"Vector_Path" %".4", i64 0, 2
  ret %"Vector_Path" %".5"
}

define %"Vector_Path" @"Vector_Path_init_capacity"(i64 %"capacity")
{
entry:
  %"if_let_result" = alloca %"Vector_Path"
  %"capacity.1" = alloca i64
  store i64 %"capacity", i64* %"capacity.1"
  %"capacity.2" = load i64, i64* %"capacity.1"
  %"letmp" = icmp sle i64 %"capacity.2", 0
  br i1 %"letmp", label %"then", label %"else"
then:
  %".5" = insertvalue {i1, %"Path"*} undef, i1 0, 0
  %".6" = insertvalue %"Vector_Path" undef, {i1, %"Path"*} %".5", 0
  %".7" = insertvalue %"Vector_Path" %".6", i64 0, 1
  %".8" = insertvalue %"Vector_Path" %".7", i64 0, 2
  br label %"ifcont"
else:
  %"capacity.3" = load i64, i64* %"capacity.1"
  %"multmp" = mul i64 %"capacity.3", 8
  %"byte_size" = alloca i64
  store i64 %"multmp", i64* %"byte_size"
  %"byte_size.1" = load i64, i64* %"byte_size"
  %"calltmp" = call i8* @"malloc"(i64 %"byte_size.1")
  %"is_not_null" = icmp ne i8* %"calltmp", null
  %"opt_flag" = insertvalue {i1, i8*} undef, i1 %"is_not_null", 0
  %"opt_val" = insertvalue {i1, i8*} %"opt_flag", i8* %"calltmp", 1
  %"is_some" = extractvalue {i1, i8*} %"opt_val", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
ifcont:
  %"iftmp" = phi  %"Vector_Path" [%".8", %"then"], [%"if_let_tmp", %"if_let_merge"]
  ret %"Vector_Path" %"iftmp"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %"opt_val", 1
  %"raw_ptr" = alloca i8*
  store i8* %"unwrapped", i8** %"raw_ptr"
  %"raw_ptr.1" = load i8*, i8** %"raw_ptr"
  %"ptrcast" = bitcast i8* %"raw_ptr.1" to %"Path"*
  %"typed_ptr" = alloca %"Path"*
  store %"Path"* %"ptrcast", %"Path"** %"typed_ptr"
  %"typed_ptr.1" = load %"Path"*, %"Path"** %"typed_ptr"
  %"capacity.4" = load i64, i64* %"capacity.1"
  %".13" = insertvalue {i1, %"Path"*} undef, i1 1, 0
  %".14" = insertvalue {i1, %"Path"*} %".13", %"Path"* %"typed_ptr.1", 1
  %".15" = insertvalue %"Vector_Path" undef, {i1, %"Path"*} %".14", 0
  %".16" = insertvalue %"Vector_Path" %".15", i64 0, 1
  %".17" = insertvalue %"Vector_Path" %".16", i64 %"capacity.4", 2
  store %"Vector_Path" %".17", %"Vector_Path"* %"if_let_result"
  br label %"if_let_merge"
if_let_else:
  %".18" = insertvalue {i1, %"Path"*} undef, i1 0, 0
  %".19" = insertvalue %"Vector_Path" undef, {i1, %"Path"*} %".18", 0
  %".20" = insertvalue %"Vector_Path" %".19", i64 0, 1
  %".21" = insertvalue %"Vector_Path" %".20", i64 0, 2
  store %"Vector_Path" %".21", %"Vector_Path"* %"if_let_result"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp" = load %"Vector_Path", %"Vector_Path"* %"if_let_result"
  br label %"ifcont"
}

define i64 @"Vector_Path_len"(%"Vector_Path" %"self")
{
entry:
  %"self.1" = alloca %"Vector_Path"
  store %"Vector_Path" %"self", %"Vector_Path"* %"self.1"
  %"self.2" = load %"Vector_Path", %"Vector_Path"* %"self.1"
  %".4" = extractvalue %"Vector_Path" %"self.2", 1
  ret i64 %".4"
}

define i1 @"Vector_Path_is_empty"(%"Vector_Path" %"self")
{
entry:
  %"self.1" = alloca %"Vector_Path"
  store %"Vector_Path" %"self", %"Vector_Path"* %"self.1"
  %"self.2" = load %"Vector_Path", %"Vector_Path"* %"self.1"
  %".4" = extractvalue %"Vector_Path" %"self.2", 1
  %"eqtmp" = icmp eq i64 %".4", 0
  ret i1 %"eqtmp"
}

define {i1, %"Path"} @"Vector_Path_get"(%"Vector_Path" %"self", i64 %"index")
{
entry:
  %"if_let_result" = alloca {i1, %"Path"}
  %"self.1" = alloca %"Vector_Path"
  store %"Vector_Path" %"self", %"Vector_Path"* %"self.1"
  %"index.1" = alloca i64
  store i64 %"index", i64* %"index.1"
  %"index.2" = load i64, i64* %"index.1"
  %"lttmp" = icmp slt i64 %"index.2", 0
  br i1 %"lttmp", label %"or_merge", label %"or_right"
or_right:
  %"index.3" = load i64, i64* %"index.1"
  %"self.2" = load %"Vector_Path", %"Vector_Path"* %"self.1"
  %".7" = extractvalue %"Vector_Path" %"self.2", 1
  %"getmp" = icmp sge i64 %"index.3", %".7"
  br label %"or_merge"
or_merge:
  %"or_result" = phi  i1 [1, %"entry"], [%"getmp", %"or_right"]
  br i1 %"or_result", label %"then", label %"else"
then:
  %".10" = insertvalue {i1, %"Path"} undef, i1 0, 0
  br label %"ifcont"
else:
  %"self.3" = load %"Vector_Path", %"Vector_Path"* %"self.1"
  %".11" = extractvalue %"Vector_Path" %"self.3", 0
  %"is_some" = extractvalue {i1, %"Path"*} %".11", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
ifcont:
  %"iftmp" = phi  {i1, %"Path"} [%".10", %"then"], [%"if_let_tmp", %"if_let_merge"]
  ret {i1, %"Path"} %"iftmp"
if_let_then:
  %"unwrapped" = extractvalue {i1, %"Path"*} %".11", 1
  %"buf" = alloca %"Path"*
  store %"Path"* %"unwrapped", %"Path"** %"buf"
  %"buf.1" = load %"Path"*, %"Path"** %"buf"
  %"index.4" = load i64, i64* %"index.1"
  %"ptr_idx" = getelementptr %"Path", %"Path"* %"buf.1", i64 %"index.4"
  %"ptr_elem" = load %"Path", %"Path"* %"ptr_idx"
  %".15" = insertvalue {i1, %"Path"} undef, i1 1, 0
  %"some_then" = insertvalue {i1, %"Path"} %".15", %"Path" %"ptr_elem", 1
  store {i1, %"Path"} %"some_then", {i1, %"Path"}* %"if_let_result"
  br label %"if_let_merge"
if_let_else:
  %".14" = insertvalue {i1, %"Path"} undef, i1 0, 0
  store {i1, %"Path"} %".14", {i1, %"Path"}* %"if_let_result"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp" = load {i1, %"Path"}, {i1, %"Path"}* %"if_let_result"
  br label %"ifcont"
}

define void @"Vector_Path_set"(%"Vector_Path"* %"self", i64 %"index", %"Path" %"value")
{
entry:
  %"index.1" = alloca i64
  store i64 %"index", i64* %"index.1"
  %"value.1" = alloca %"Path"
  store %"Path" %"value", %"Path"* %"value.1"
  %"index.2" = load i64, i64* %"index.1"
  %"getmp" = icmp sge i64 %"index.2", 0
  br i1 %"getmp", label %"and_right", label %"and_merge"
and_right:
  %"index.3" = load i64, i64* %"index.1"
  %"self.1" = load %"Vector_Path", %"Vector_Path"* %"self"
  %".8" = extractvalue %"Vector_Path" %"self.1", 1
  %"lttmp" = icmp slt i64 %"index.3", %".8"
  br label %"and_merge"
and_merge:
  %"and_result" = phi  i1 [0, %"entry"], [%"lttmp", %"and_right"]
  br i1 %"and_result", label %"then", label %"else"
then:
  %"self.2" = load %"Vector_Path", %"Vector_Path"* %"self"
  %".11" = extractvalue %"Vector_Path" %"self.2", 0
  %"is_some" = extractvalue {i1, %"Path"*} %".11", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
else:
  br label %"ifcont"
ifcont:
  ret void
if_let_then:
  %"unwrapped" = extractvalue {i1, %"Path"*} %".11", 1
  %"buf" = alloca %"Path"*
  store %"Path"* %"unwrapped", %"Path"** %"buf"
  %"value.2" = load %"Path", %"Path"* %"value.1"
  %"index.4" = load i64, i64* %"index.1"
  %"container" = load %"Path"*, %"Path"** %"buf"
  %"ptr_elem" = getelementptr %"Path", %"Path"* %"container", i64 %"index.4"
  store %"Path" %"value.2", %"Path"* %"ptr_elem"
  br label %"if_let_merge"
if_let_else:
  br label %"if_let_merge"
if_let_merge:
  br label %"ifcont"
}

define void @"Vector_Path_push"(%"Vector_Path"* %"self", %"Path" %"value")
{
entry:
  %"value.1" = alloca %"Path"
  store %"Path" %"value", %"Path"* %"value.1"
  %"self.1" = load %"Vector_Path", %"Vector_Path"* %"self"
  %".5" = extractvalue %"Vector_Path" %"self.1", 1
  %"self.2" = load %"Vector_Path", %"Vector_Path"* %"self"
  %".6" = extractvalue %"Vector_Path" %"self.2", 2
  %"getmp" = icmp sge i64 %".5", %".6"
  br i1 %"getmp", label %"then", label %"else"
then:
  %"self.3" = load %"Vector_Path", %"Vector_Path"* %"self"
  call void @"Vector_Path_grow"(%"Vector_Path"* %"self")
  br label %"ifcont"
else:
  br label %"ifcont"
ifcont:
  %"self.4" = load %"Vector_Path", %"Vector_Path"* %"self"
  %".10" = extractvalue %"Vector_Path" %"self.4", 0
  %"is_some" = extractvalue {i1, %"Path"*} %".10", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, %"Path"*} %".10", 1
  %"buf" = alloca %"Path"*
  store %"Path"* %"unwrapped", %"Path"** %"buf"
  %"value.2" = load %"Path", %"Path"* %"value.1"
  %"self.5" = load %"Vector_Path", %"Vector_Path"* %"self"
  %".13" = extractvalue %"Vector_Path" %"self.5", 1
  %"container" = load %"Path"*, %"Path"** %"buf"
  %"ptr_elem" = getelementptr %"Path", %"Path"* %"container", i64 %".13"
  store %"Path" %"value.2", %"Path"* %"ptr_elem"
  %"self.6" = load %"Vector_Path", %"Vector_Path"* %"self"
  %".15" = extractvalue %"Vector_Path" %"self.6", 1
  %"addtmp" = add i64 %".15", 1
  %"length_ptr" = getelementptr %"Vector_Path", %"Vector_Path"* %"self", i32 0, i32 1
  store i64 %"addtmp", i64* %"length_ptr"
  br label %"if_let_merge"
if_let_else:
  br label %"if_let_merge"
if_let_merge:
  ret void
}

define {i1, %"Path"} @"Vector_Path_pop"(%"Vector_Path"* %"self")
{
entry:
  %"if_let_result" = alloca {i1, %"Path"}
  %"self.1" = load %"Vector_Path", %"Vector_Path"* %"self"
  %".3" = extractvalue %"Vector_Path" %"self.1", 1
  %"eqtmp" = icmp eq i64 %".3", 0
  br i1 %"eqtmp", label %"then", label %"else"
then:
  %".5" = insertvalue {i1, %"Path"} undef, i1 0, 0
  br label %"ifcont"
else:
  %"self.2" = load %"Vector_Path", %"Vector_Path"* %"self"
  %".6" = extractvalue %"Vector_Path" %"self.2", 1
  %"subtmp" = sub i64 %".6", 1
  %"length_ptr" = getelementptr %"Vector_Path", %"Vector_Path"* %"self", i32 0, i32 1
  store i64 %"subtmp", i64* %"length_ptr"
  %"self.3" = load %"Vector_Path", %"Vector_Path"* %"self"
  %".8" = extractvalue %"Vector_Path" %"self.3", 0
  %"is_some" = extractvalue {i1, %"Path"*} %".8", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
ifcont:
  %"iftmp" = phi  {i1, %"Path"} [%".5", %"then"], [%"if_let_tmp", %"if_let_merge"]
  ret {i1, %"Path"} %"iftmp"
if_let_then:
  %"unwrapped" = extractvalue {i1, %"Path"*} %".8", 1
  %"buf" = alloca %"Path"*
  store %"Path"* %"unwrapped", %"Path"** %"buf"
  %"buf.1" = load %"Path"*, %"Path"** %"buf"
  %"self.4" = load %"Vector_Path", %"Vector_Path"* %"self"
  %".11" = extractvalue %"Vector_Path" %"self.4", 1
  %"ptr_idx" = getelementptr %"Path", %"Path"* %"buf.1", i64 %".11"
  %"ptr_elem" = load %"Path", %"Path"* %"ptr_idx"
  %".13" = insertvalue {i1, %"Path"} undef, i1 1, 0
  %"some_then" = insertvalue {i1, %"Path"} %".13", %"Path" %"ptr_elem", 1
  store {i1, %"Path"} %"some_then", {i1, %"Path"}* %"if_let_result"
  br label %"if_let_merge"
if_let_else:
  %".12" = insertvalue {i1, %"Path"} undef, i1 0, 0
  store {i1, %"Path"} %".12", {i1, %"Path"}* %"if_let_result"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp" = load {i1, %"Path"}, {i1, %"Path"}* %"if_let_result"
  br label %"ifcont"
}

define void @"Vector_Path_clear"(%"Vector_Path"* %"self")
{
entry:
  %"length_ptr" = getelementptr %"Vector_Path", %"Vector_Path"* %"self", i32 0, i32 1
  store i64 0, i64* %"length_ptr"
  ret void
}

define void @"Vector_Path_grow"(%"Vector_Path"* %"self")
{
entry:
  %"self.1" = load %"Vector_Path", %"Vector_Path"* %"self"
  %".3" = extractvalue %"Vector_Path" %"self.1", 2
  %"eqtmp" = icmp eq i64 %".3", 0
  br i1 %"eqtmp", label %"then", label %"else"
then:
  br label %"ifcont"
else:
  %"self.2" = load %"Vector_Path", %"Vector_Path"* %"self"
  %".5" = extractvalue %"Vector_Path" %"self.2", 2
  %"multmp" = mul i64 %".5", 2
  br label %"ifcont"
ifcont:
  %"iftmp" = phi  i64 [4, %"then"], [%"multmp", %"else"]
  %"new_capacity" = alloca i64
  store i64 %"iftmp", i64* %"new_capacity"
  %"new_capacity.1" = load i64, i64* %"new_capacity"
  %"multmp.1" = mul i64 %"new_capacity.1", 8
  %"new_byte_size" = alloca i64
  store i64 %"multmp.1", i64* %"new_byte_size"
  %"self.3" = load %"Vector_Path", %"Vector_Path"* %"self"
  %".10" = extractvalue %"Vector_Path" %"self.3", 0
  %"is_some" = extractvalue {i1, %"Path"*} %".10", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, %"Path"*} %".10", 1
  %"buf" = alloca %"Path"*
  store %"Path"* %"unwrapped", %"Path"** %"buf"
  %"buf.1" = load %"Path"*, %"Path"** %"buf"
  %"ptrcast" = bitcast %"Path"* %"buf.1" to i8*
  %"raw_ptr" = alloca i8*
  store i8* %"ptrcast", i8** %"raw_ptr"
  %"raw_ptr.1" = load i8*, i8** %"raw_ptr"
  %"new_byte_size.1" = load i64, i64* %"new_byte_size"
  %"calltmp" = call i8* @"realloc"(i8* %"raw_ptr.1", i64 %"new_byte_size.1")
  %"is_not_null" = icmp ne i8* %"calltmp", null
  %"opt_flag" = insertvalue {i1, i8*} undef, i1 %"is_not_null", 0
  %"opt_val" = insertvalue {i1, i8*} %"opt_flag", i8* %"calltmp", 1
  %"is_some.1" = extractvalue {i1, i8*} %"opt_val", 0
  br i1 %"is_some.1", label %"if_let_then.1", label %"if_let_else.1"
if_let_else:
  %"new_byte_size.2" = load i64, i64* %"new_byte_size"
  %"calltmp.1" = call i8* @"malloc"(i64 %"new_byte_size.2")
  %"is_not_null.1" = icmp ne i8* %"calltmp.1", null
  %"opt_flag.1" = insertvalue {i1, i8*} undef, i1 %"is_not_null.1", 0
  %"opt_val.1" = insertvalue {i1, i8*} %"opt_flag.1", i8* %"calltmp.1", 1
  %"is_some.2" = extractvalue {i1, i8*} %"opt_val.1", 0
  br i1 %"is_some.2", label %"if_let_then.2", label %"if_let_else.2"
if_let_merge:
  ret void
if_let_then.1:
  %"unwrapped.1" = extractvalue {i1, i8*} %"opt_val", 1
  %"new_raw" = alloca i8*
  store i8* %"unwrapped.1", i8** %"new_raw"
  %"new_raw.1" = load i8*, i8** %"new_raw"
  %"ptrcast.1" = bitcast i8* %"new_raw.1" to %"Path"*
  %"buffer_ptr" = getelementptr %"Vector_Path", %"Vector_Path"* %"self", i32 0, i32 0
  %".16" = insertvalue {i1, %"Path"*} undef, i1 1, 0
  %".17" = insertvalue {i1, %"Path"*} %".16", %"Path"* %"ptrcast.1", 1
  store {i1, %"Path"*} %".17", {i1, %"Path"*}* %"buffer_ptr"
  %"new_capacity.2" = load i64, i64* %"new_capacity"
  %"capacity_ptr" = getelementptr %"Vector_Path", %"Vector_Path"* %"self", i32 0, i32 2
  store i64 %"new_capacity.2", i64* %"capacity_ptr"
  br label %"if_let_merge.1"
if_let_else.1:
  br label %"if_let_merge.1"
if_let_merge.1:
  br label %"if_let_merge"
if_let_then.2:
  %"unwrapped.2" = extractvalue {i1, i8*} %"opt_val.1", 1
  %"raw_ptr.2" = alloca i8*
  store i8* %"unwrapped.2", i8** %"raw_ptr.2"
  %"raw_ptr.3" = load i8*, i8** %"raw_ptr.2"
  %"ptrcast.2" = bitcast i8* %"raw_ptr.3" to %"Path"*
  %"buffer_ptr.1" = getelementptr %"Vector_Path", %"Vector_Path"* %"self", i32 0, i32 0
  %".24" = insertvalue {i1, %"Path"*} undef, i1 1, 0
  %".25" = insertvalue {i1, %"Path"*} %".24", %"Path"* %"ptrcast.2", 1
  store {i1, %"Path"*} %".25", {i1, %"Path"*}* %"buffer_ptr.1"
  %"new_capacity.3" = load i64, i64* %"new_capacity"
  %"capacity_ptr.1" = getelementptr %"Vector_Path", %"Vector_Path"* %"self", i32 0, i32 2
  store i64 %"new_capacity.3", i64* %"capacity_ptr.1"
  br label %"if_let_merge.2"
if_let_else.2:
  br label %"if_let_merge.2"
if_let_merge.2:
  br label %"if_let_merge"
}

define {i1, %"Path"} @"VectorIterator_Path_next"(%"VectorIterator_Path"* %"self")
{
entry:
  %"if_let_result" = alloca {i1, %"Path"}
  %"self.1" = load %"VectorIterator_Path", %"VectorIterator_Path"* %"self"
  %".3" = extractvalue %"VectorIterator_Path" %"self.1", 2
  %"self.2" = load %"VectorIterator_Path", %"VectorIterator_Path"* %"self"
  %".4" = extractvalue %"VectorIterator_Path" %"self.2", 1
  %"lttmp" = icmp slt i64 %".3", %".4"
  br i1 %"lttmp", label %"then", label %"else"
then:
  %"self.3" = load %"VectorIterator_Path", %"VectorIterator_Path"* %"self"
  %".6" = extractvalue %"VectorIterator_Path" %"self.3", 2
  %"idx" = alloca i64
  store i64 %".6", i64* %"idx"
  %"self.4" = load %"VectorIterator_Path", %"VectorIterator_Path"* %"self"
  %".8" = extractvalue %"VectorIterator_Path" %"self.4", 2
  %"addtmp" = add i64 %".8", 1
  %"index_ptr" = getelementptr %"VectorIterator_Path", %"VectorIterator_Path"* %"self", i32 0, i32 2
  store i64 %"addtmp", i64* %"index_ptr"
  %"self.5" = load %"VectorIterator_Path", %"VectorIterator_Path"* %"self"
  %".10" = extractvalue %"VectorIterator_Path" %"self.5", 0
  %"is_some" = extractvalue {i1, %"Path"*} %".10", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
else:
  %".19" = insertvalue {i1, %"Path"} undef, i1 0, 0
  br label %"ifcont"
ifcont:
  %"iftmp" = phi  {i1, %"Path"} [%"if_let_tmp", %"if_let_merge"], [%".19", %"else"]
  ret {i1, %"Path"} %"iftmp"
if_let_then:
  %"unwrapped" = extractvalue {i1, %"Path"*} %".10", 1
  %"buf" = alloca %"Path"*
  store %"Path"* %"unwrapped", %"Path"** %"buf"
  %"buf.1" = load %"Path"*, %"Path"** %"buf"
  %"idx.1" = load i64, i64* %"idx"
  %"ptr_idx" = getelementptr %"Path", %"Path"* %"buf.1", i64 %"idx.1"
  %"ptr_elem" = load %"Path", %"Path"* %"ptr_idx"
  %".14" = insertvalue {i1, %"Path"} undef, i1 1, 0
  %"some_then" = insertvalue {i1, %"Path"} %".14", %"Path" %"ptr_elem", 1
  store {i1, %"Path"} %"some_then", {i1, %"Path"}* %"if_let_result"
  br label %"if_let_merge"
if_let_else:
  %".13" = insertvalue {i1, %"Path"} undef, i1 0, 0
  store {i1, %"Path"} %".13", {i1, %"Path"}* %"if_let_result"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp" = load {i1, %"Path"}, {i1, %"Path"}* %"if_let_result"
  br label %"ifcont"
}

define %"VectorIterator_Path" @"Vector_Path_iter"(%"Vector_Path" %"self")
{
entry:
  %"self.1" = alloca %"Vector_Path"
  store %"Vector_Path" %"self", %"Vector_Path"* %"self.1"
  %"self.2" = load %"Vector_Path", %"Vector_Path"* %"self.1"
  %".4" = extractvalue %"Vector_Path" %"self.2", 0
  %"self.3" = load %"Vector_Path", %"Vector_Path"* %"self.1"
  %".5" = extractvalue %"Vector_Path" %"self.3", 1
  %".6" = insertvalue %"VectorIterator_Path" undef, {i1, %"Path"*} %".4", 0
  %".7" = insertvalue %"VectorIterator_Path" %".6", i64 %".5", 1
  %".8" = insertvalue %"VectorIterator_Path" %".7", i64 0, 2
  ret %"VectorIterator_Path" %".8"
}

define void @"Vector_Path_deinit"(%"Vector_Path"* %"self")
{
entry:
  %"self.1" = load %"Vector_Path", %"Vector_Path"* %"self"
  %".3" = extractvalue %"Vector_Path" %"self.1", 0
  %"is_some" = extractvalue {i1, %"Path"*} %".3", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, %"Path"*} %".3", 1
  %"buf" = alloca %"Path"*
  store %"Path"* %"unwrapped", %"Path"** %"buf"
  %"buf.1" = load %"Path"*, %"Path"** %"buf"
  %"ptrcast" = bitcast %"Path"* %"buf.1" to i8*
  %"raw_ptr" = alloca i8*
  store i8* %"ptrcast", i8** %"raw_ptr"
  %"raw_ptr.1" = load i8*, i8** %"raw_ptr"
  call void @"free"(i8* %"raw_ptr.1")
  br label %"if_let_merge"
if_let_else:
  br label %"if_let_merge"
if_let_merge:
  ret void
}

define {i1, %"Vector_Path"} @"Directory_list"(%"Path" %"path")
{
entry:
  %"if_let_result" = alloca {i1, %"Vector_Path"}
  %"path.1" = alloca %"Path"
  store %"Path" %"path", %"Path"* %"path.1"
  %"path.2" = load %"Path", %"Path"* %"path.1"
  %"methodcall" = call i8* @"Path_as_str"(%"Path" %"path.2")
  %"path_ptr" = alloca i8*
  store i8* %"methodcall", i8** %"path_ptr"
  %"path_ptr.1" = load i8*, i8** %"path_ptr"
  %"calltmp" = call i8* @"opendir"(i8* %"path_ptr.1")
  %"is_not_null" = icmp ne i8* %"calltmp", null
  %"opt_flag" = insertvalue {i1, i8*} undef, i1 %"is_not_null", 0
  %"opt_val" = insertvalue {i1, i8*} %"opt_flag", i8* %"calltmp", 1
  %"is_some" = extractvalue {i1, i8*} %"opt_val", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %"opt_val", 1
  %"dir" = alloca i8*
  store i8* %"unwrapped", i8** %"dir"
  %".7" = call %"Vector_Path" @"Vector_Path_init_"()
  %"result" = alloca %"Vector_Path"
  store %"Vector_Path" %".7", %"Vector_Path"* %"result"
  %"done" = alloca i1
  store i1 0, i1* %"done"
  br label %"while.cond"
if_let_else:
  %".34" = insertvalue {i1, %"Vector_Path"} undef, i1 0, 0
  store {i1, %"Vector_Path"} %".34", {i1, %"Vector_Path"}* %"if_let_result"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp" = load {i1, %"Vector_Path"}, {i1, %"Vector_Path"}* %"if_let_result"
  ret {i1, %"Vector_Path"} %"if_let_tmp"
while.cond:
  %"done.1" = load i1, i1* %"done"
  %"nottmp" = xor i1 %"done.1", 1
  br i1 %"nottmp", label %"while.body", label %"while.end"
while.body:
  %"dir.1" = load i8*, i8** %"dir"
  %"calltmp.1" = call i8* @"readdir"(i8* %"dir.1")
  %"is_not_null.1" = icmp ne i8* %"calltmp.1", null
  %"opt_flag.1" = insertvalue {i1, i8*} undef, i1 %"is_not_null.1", 0
  %"opt_val.1" = insertvalue {i1, i8*} %"opt_flag.1", i8* %"calltmp.1", 1
  %"is_some.1" = extractvalue {i1, i8*} %"opt_val.1", 0
  br i1 %"is_some.1", label %"if_let_then.1", label %"if_let_else.1"
while.end:
  %"dir.2" = load i8*, i8** %"dir"
  %"calltmp.2" = call i32 @"closedir"(i8* %"dir.2")
  %"result_moved" = load %"Vector_Path", %"Vector_Path"* %"result"
  %".35" = insertvalue {i1, %"Vector_Path"} undef, i1 1, 0
  %"some_then" = insertvalue {i1, %"Vector_Path"} %".35", %"Vector_Path" %"result_moved", 1
  store {i1, %"Vector_Path"} %"some_then", {i1, %"Vector_Path"}* %"if_let_result"
  br label %"if_let_merge"
if_let_then.1:
  %"unwrapped.1" = extractvalue {i1, i8*} %"opt_val.1", 1
  %"entry.1" = alloca i8*
  store i8* %"unwrapped.1", i8** %"entry.1"
  %"entry.2" = load i8*, i8** %"entry.1"
  %"ptr_add" = getelementptr i8, i8* %"entry.2", i64 21
  %"name_ptr" = alloca i8*
  store i8* %"ptr_add", i8** %"name_ptr"
  %"name_ptr.1" = load i8*, i8** %"name_ptr"
  %"name" = alloca i8*
  store i8* %"name_ptr.1", i8** %"name"
  %"name_ptr.2" = load i8*, i8** %"name_ptr"
  %"ptr_idx" = getelementptr i8, i8* %"name_ptr.2", i64 0
  %"ptr_elem" = load i8, i8* %"ptr_idx"
  %"first_char" = alloca i8
  store i8 %"ptr_elem", i8* %"first_char"
  %"first_char.1" = load i8, i8* %"first_char"
  %"trunc" = trunc i64 46 to i8
  %"eqtmp" = icmp eq i8 %"first_char.1", %"trunc"
  br i1 %"eqtmp", label %"then", label %"else"
if_let_else.1:
  store i1 1, i1* %"done"
  br label %"if_let_merge.1"
if_let_merge.1:
  br label %"while.cond"
then:
  %"name_ptr.3" = load i8*, i8** %"name_ptr"
  %"ptr_idx.1" = getelementptr i8, i8* %"name_ptr.3", i64 1
  %"ptr_elem.1" = load i8, i8* %"ptr_idx.1"
  %"second_char" = alloca i8
  store i8 %"ptr_elem.1", i8* %"second_char"
  %"second_char.1" = load i8, i8* %"second_char"
  %"trunc.1" = trunc i64 0 to i8
  %"eqtmp.1" = icmp eq i8 %"second_char.1", %"trunc.1"
  br i1 %"eqtmp.1", label %"then.1", label %"else.1"
else:
  br label %"ifcont"
ifcont:
  %"path.3" = load %"Path", %"Path"* %"path.1"
  %"name.1" = load i8*, i8** %"name"
  %"methodcall.1" = call %"Path" @"Path_join"(%"Path" %"path.3", i8* %"name.1")
  %"full_path" = alloca %"Path"
  store %"Path" %"methodcall.1", %"Path"* %"full_path"
  %"result.1" = load %"Vector_Path", %"Vector_Path"* %"result"
  %"full_path.1" = load %"Path", %"Path"* %"full_path"
  call void @"Vector_Path_push"(%"Vector_Path"* %"result", %"Path" %"full_path.1")
  br label %"if_let_merge.1"
then.1:
  br label %"while.cond"
else.1:
  br label %"ifcont.1"
ifcont.1:
  %"second_char.2" = load i8, i8* %"second_char"
  %"trunc.2" = trunc i64 46 to i8
  %"eqtmp.2" = icmp eq i8 %"second_char.2", %"trunc.2"
  br i1 %"eqtmp.2", label %"and_right", label %"and_merge"
and_right:
  %"name_ptr.4" = load i8*, i8** %"name_ptr"
  %"ptr_idx.2" = getelementptr i8, i8* %"name_ptr.4", i64 2
  %"ptr_elem.2" = load i8, i8* %"ptr_idx.2"
  %"trunc.3" = trunc i64 0 to i8
  %"eqtmp.3" = icmp eq i8 %"ptr_elem.2", %"trunc.3"
  br label %"and_merge"
and_merge:
  %"and_result" = phi  i1 [0, %"ifcont.1"], [%"eqtmp.3", %"and_right"]
  br i1 %"and_result", label %"then.2", label %"else.2"
then.2:
  br label %"while.cond"
else.2:
  br label %"ifcont.2"
ifcont.2:
  br label %"ifcont"
}

define i1 @"Directory_create"(%"Path" %"path")
{
entry:
  %"path.1" = alloca %"Path"
  store %"Path" %"path", %"Path"* %"path.1"
  %"path.2" = load %"Path", %"Path"* %"path.1"
  %"methodcall" = call i8* @"Path_as_str"(%"Path" %"path.2")
  %"path_ptr" = alloca i8*
  store i8* %"methodcall", i8** %"path_ptr"
  %"path_ptr.1" = load i8*, i8** %"path_ptr"
  %"calltmp" = call i32 @"mkdir"(i8* %"path_ptr.1", i64 493)
  %"trunc" = trunc i64 0 to i32
  %"eqtmp" = icmp eq i32 %"calltmp", %"trunc"
  ret i1 %"eqtmp"
}

define i1 @"Directory_remove"(%"Path" %"path")
{
entry:
  %"path.1" = alloca %"Path"
  store %"Path" %"path", %"Path"* %"path.1"
  %"path.2" = load %"Path", %"Path"* %"path.1"
  %"methodcall" = call i8* @"Path_as_str"(%"Path" %"path.2")
  %"path_ptr" = alloca i8*
  store i8* %"methodcall", i8** %"path_ptr"
  %"path_ptr.1" = load i8*, i8** %"path_ptr"
  %"calltmp" = call i32 @"rmdir"(i8* %"path_ptr.1")
  %"trunc" = trunc i64 0 to i32
  %"eqtmp" = icmp eq i32 %"calltmp", %"trunc"
  ret i1 %"eqtmp"
}

define i1 @"Directory_exists"(%"Path" %"path")
{
entry:
  %"path.1" = alloca %"Path"
  store %"Path" %"path", %"Path"* %"path.1"
  %"path.2" = load %"Path", %"Path"* %"path.1"
  %"methodcall" = call i8* @"Path_as_str"(%"Path" %"path.2")
  %"ptr" = alloca i8*
  store i8* %"methodcall", i8** %"ptr"
  %"ptr.1" = load i8*, i8** %"ptr"
  %"trunc" = trunc i64 0 to i32
  %"calltmp" = call i32 @"access"(i8* %"ptr.1", i32 %"trunc")
  %"trunc.1" = trunc i64 0 to i32
  %"eqtmp" = icmp eq i32 %"calltmp", %"trunc.1"
  ret i1 %"eqtmp"
}

define {i1, %"Path"} @"Directory_current"()
{
entry:
  %"if_let_result.1" = alloca {i1, %"Path"}
  %"if_let_result" = alloca {i1, %"Path"}
  %"calltmp" = call i8* @"malloc"(i64 1024)
  %"is_not_null" = icmp ne i8* %"calltmp", null
  %"opt_flag" = insertvalue {i1, i8*} undef, i1 %"is_not_null", 0
  %"opt_val" = insertvalue {i1, i8*} %"opt_flag", i8* %"calltmp", 1
  %"is_some" = extractvalue {i1, i8*} %"opt_val", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %"opt_val", 1
  %"buf" = alloca i8*
  store i8* %"unwrapped", i8** %"buf"
  %"buf.1" = load i8*, i8** %"buf"
  %"calltmp.1" = call i8* @"getcwd"(i8* %"buf.1", i64 1024)
  %"is_not_null.1" = icmp ne i8* %"calltmp.1", null
  %"opt_flag.1" = insertvalue {i1, i8*} undef, i1 %"is_not_null.1", 0
  %"opt_val.1" = insertvalue {i1, i8*} %"opt_flag.1", i8* %"calltmp.1", 1
  %"is_some.1" = extractvalue {i1, i8*} %"opt_val.1", 0
  br i1 %"is_some.1", label %"if_let_then.1", label %"if_let_else.1"
if_let_else:
  %".13" = insertvalue {i1, %"Path"} undef, i1 0, 0
  store {i1, %"Path"} %".13", {i1, %"Path"}* %"if_let_result.1"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp.1" = load {i1, %"Path"}, {i1, %"Path"}* %"if_let_result.1"
  ret {i1, %"Path"} %"if_let_tmp.1"
if_let_then.1:
  %"unwrapped.1" = extractvalue {i1, i8*} %"opt_val.1", 1
  %"result" = alloca i8*
  store i8* %"unwrapped.1", i8** %"result"
  %"result.1" = load i8*, i8** %"result"
  %".6" = call %"Path" @"Path_init_s"(i8* %"result.1")
  %".8" = insertvalue {i1, %"Path"} undef, i1 1, 0
  %"some_then" = insertvalue {i1, %"Path"} %".8", %"Path" %".6", 1
  store {i1, %"Path"} %"some_then", {i1, %"Path"}* %"if_let_result"
  br label %"if_let_merge.1"
if_let_else.1:
  %"buf.2" = load i8*, i8** %"buf"
  call void @"free"(i8* %"buf.2")
  %".7" = insertvalue {i1, %"Path"} undef, i1 0, 0
  store {i1, %"Path"} %".7", {i1, %"Path"}* %"if_let_result"
  br label %"if_let_merge.1"
if_let_merge.1:
  %"if_let_tmp" = load {i1, %"Path"}, {i1, %"Path"}* %"if_let_result"
  store {i1, %"Path"} %"if_let_tmp", {i1, %"Path"}* %"if_let_result.1"
  br label %"if_let_merge"
}

define i1 @"Directory_set_current"(%"Path" %"path")
{
entry:
  %"path.1" = alloca %"Path"
  store %"Path" %"path", %"Path"* %"path.1"
  %"path.2" = load %"Path", %"Path"* %"path.1"
  %"methodcall" = call i8* @"Path_as_str"(%"Path" %"path.2")
  %"path_ptr" = alloca i8*
  store i8* %"methodcall", i8** %"path_ptr"
  %"path_ptr.1" = load i8*, i8** %"path_ptr"
  %"calltmp" = call i32 @"chdir"(i8* %"path_ptr.1")
  %"trunc" = trunc i64 0 to i32
  %"eqtmp" = icmp eq i32 %"calltmp", %"trunc"
  ret i1 %"eqtmp"
}

define i64 @"Env_argc"()
{
entry:
  %"calltmp" = call i8* @"_NSGetArgc"()
  %"ptrcast" = bitcast i8* %"calltmp" to i32*
  %"argc_ptr" = alloca i32*
  store i32* %"ptrcast", i32** %"argc_ptr"
  %"argc_ptr.1" = load i32*, i32** %"argc_ptr"
  %"ptr_idx" = getelementptr i32, i32* %"argc_ptr.1", i64 0
  %"ptr_elem" = load i32, i32* %"ptr_idx"
  %"zext" = zext i32 %"ptr_elem" to i64
  ret i64 %"zext"
}

define {i1, i8*} @"Env_arg"(i64 %"index")
{
entry:
  %"index.1" = alloca i64
  store i64 %"index", i64* %"index.1"
  %"static_methodcall" = call i64 @"Env_argc"()
  %"argc" = alloca i64
  store i64 %"static_methodcall", i64* %"argc"
  %"index.2" = load i64, i64* %"index.1"
  %"lttmp" = icmp slt i64 %"index.2", 0
  br i1 %"lttmp", label %"or_merge", label %"or_right"
or_right:
  %"index.3" = load i64, i64* %"index.1"
  %"argc.1" = load i64, i64* %"argc"
  %"getmp" = icmp sge i64 %"index.3", %"argc.1"
  br label %"or_merge"
or_merge:
  %"or_result" = phi  i1 [1, %"entry"], [%"getmp", %"or_right"]
  br i1 %"or_result", label %"then", label %"else"
then:
  %".8" = insertvalue {i1, i8*} undef, i1 0, 0
  ret {i1, i8*} %".8"
else:
  br label %"ifcont"
ifcont:
  %"calltmp" = call i8* @"_NSGetArgv"()
  %"ptrcast" = bitcast i8* %"calltmp" to i8**
  %"argv_ptr_ptr" = alloca i8**
  store i8** %"ptrcast", i8*** %"argv_ptr_ptr"
  %"argv_ptr_ptr.1" = load i8**, i8*** %"argv_ptr_ptr"
  %"ptr_idx" = getelementptr i8*, i8** %"argv_ptr_ptr.1", i64 0
  %"ptr_elem" = load i8*, i8** %"ptr_idx"
  %"argv" = alloca i8*
  store i8* %"ptr_elem", i8** %"argv"
  %"argv.1" = load i8*, i8** %"argv"
  %"ptrcast.1" = bitcast i8* %"argv.1" to i8**
  %"argv_as_ptr_array" = alloca i8**
  store i8** %"ptrcast.1", i8*** %"argv_as_ptr_array"
  %"argv_as_ptr_array.1" = load i8**, i8*** %"argv_as_ptr_array"
  %"index.4" = load i64, i64* %"index.1"
  %"ptr_idx.1" = getelementptr i8*, i8** %"argv_as_ptr_array.1", i64 %"index.4"
  %"ptr_elem.1" = load i8*, i8** %"ptr_idx.1"
  %"arg_ptr" = alloca i8*
  store i8* %"ptr_elem.1", i8** %"arg_ptr"
  %"arg_ptr.1" = load i8*, i8** %"arg_ptr"
  %".15" = insertvalue {i1, i8*} undef, i1 1, 0
  %".16" = insertvalue {i1, i8*} %".15", i8* %"arg_ptr.1", 1
  ret {i1, i8*} %".16"
}

define {i1, i8*} @"Vector_String_swap_remove"(%"Vector_String"* %"self", i64 %"index")
{
entry:
  %"if_let_result" = alloca {i1, i8*}
  %"index.1" = alloca i64
  store i64 %"index", i64* %"index.1"
  %"index.2" = load i64, i64* %"index.1"
  %"lttmp" = icmp slt i64 %"index.2", 0
  br i1 %"lttmp", label %"or_merge", label %"or_right"
or_right:
  %"index.3" = load i64, i64* %"index.1"
  %"self.1" = load %"Vector_String", %"Vector_String"* %"self"
  %".6" = extractvalue %"Vector_String" %"self.1", 1
  %"getmp" = icmp sge i64 %"index.3", %".6"
  br label %"or_merge"
or_merge:
  %"or_result" = phi  i1 [1, %"entry"], [%"getmp", %"or_right"]
  br i1 %"or_result", label %"then", label %"else"
then:
  %".9" = insertvalue {i1, i8*} undef, i1 0, 0
  br label %"ifcont"
else:
  %"self.2" = load %"Vector_String", %"Vector_String"* %"self"
  %".10" = extractvalue %"Vector_String" %"self.2", 0
  %"is_some" = extractvalue {i1, i8**} %".10", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
ifcont:
  %"iftmp" = phi  {i1, i8*} [%".9", %"then"], [%"if_let_tmp", %"if_let_merge"]
  ret {i1, i8*} %"iftmp"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8**} %".10", 1
  %"buf" = alloca i8**
  store i8** %"unwrapped", i8*** %"buf"
  %"buf.1" = load i8**, i8*** %"buf"
  %"index.4" = load i64, i64* %"index.1"
  %"ptr_idx" = getelementptr i8*, i8** %"buf.1", i64 %"index.4"
  %"ptr_elem" = load i8*, i8** %"ptr_idx"
  %"removed" = alloca i8*
  store i8* %"ptr_elem", i8** %"removed"
  %"index.5" = load i64, i64* %"index.1"
  %"self.3" = load %"Vector_String", %"Vector_String"* %"self"
  %".14" = extractvalue %"Vector_String" %"self.3", 1
  %"subtmp" = sub i64 %".14", 1
  %"lttmp.1" = icmp slt i64 %"index.5", %"subtmp"
  br i1 %"lttmp.1", label %"then.1", label %"else.1"
if_let_else:
  %".22" = insertvalue {i1, i8*} undef, i1 0, 0
  store {i1, i8*} %".22", {i1, i8*}* %"if_let_result"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp" = load {i1, i8*}, {i1, i8*}* %"if_let_result"
  br label %"ifcont"
then.1:
  %"buf.2" = load i8**, i8*** %"buf"
  %"self.4" = load %"Vector_String", %"Vector_String"* %"self"
  %".16" = extractvalue %"Vector_String" %"self.4", 1
  %"subtmp.1" = sub i64 %".16", 1
  %"ptr_idx.1" = getelementptr i8*, i8** %"buf.2", i64 %"subtmp.1"
  %"ptr_elem.1" = load i8*, i8** %"ptr_idx.1"
  %"index.6" = load i64, i64* %"index.1"
  %"container" = load i8**, i8*** %"buf"
  %"ptr_elem.2" = getelementptr i8*, i8** %"container", i64 %"index.6"
  store i8* %"ptr_elem.1", i8** %"ptr_elem.2"
  br label %"ifcont.1"
else.1:
  br label %"ifcont.1"
ifcont.1:
  %"self.5" = load %"Vector_String", %"Vector_String"* %"self"
  %".20" = extractvalue %"Vector_String" %"self.5", 1
  %"subtmp.2" = sub i64 %".20", 1
  %"length_ptr" = getelementptr %"Vector_String", %"Vector_String"* %"self", i32 0, i32 1
  store i64 %"subtmp.2", i64* %"length_ptr"
  %"removed.1" = load i8*, i8** %"removed"
  %".23" = insertvalue {i1, i8*} undef, i1 1, 0
  %"some_then" = insertvalue {i1, i8*} %".23", i8* %"removed.1", 1
  store {i1, i8*} %"some_then", {i1, i8*}* %"if_let_result"
  br label %"if_let_merge"
}

define %"Vector_String" @"Vector_String_init_"()
{
entry:
  %".2" = insertvalue {i1, i8**} undef, i1 0, 0
  %".3" = insertvalue %"Vector_String" undef, {i1, i8**} %".2", 0
  %".4" = insertvalue %"Vector_String" %".3", i64 0, 1
  %".5" = insertvalue %"Vector_String" %".4", i64 0, 2
  ret %"Vector_String" %".5"
}

define %"Vector_String" @"Vector_String_init_capacity"(i64 %"capacity")
{
entry:
  %"if_let_result" = alloca %"Vector_String"
  %"capacity.1" = alloca i64
  store i64 %"capacity", i64* %"capacity.1"
  %"capacity.2" = load i64, i64* %"capacity.1"
  %"letmp" = icmp sle i64 %"capacity.2", 0
  br i1 %"letmp", label %"then", label %"else"
then:
  %".5" = insertvalue {i1, i8**} undef, i1 0, 0
  %".6" = insertvalue %"Vector_String" undef, {i1, i8**} %".5", 0
  %".7" = insertvalue %"Vector_String" %".6", i64 0, 1
  %".8" = insertvalue %"Vector_String" %".7", i64 0, 2
  br label %"ifcont"
else:
  %"capacity.3" = load i64, i64* %"capacity.1"
  %"multmp" = mul i64 %"capacity.3", 8
  %"byte_size" = alloca i64
  store i64 %"multmp", i64* %"byte_size"
  %"byte_size.1" = load i64, i64* %"byte_size"
  %"calltmp" = call i8* @"malloc"(i64 %"byte_size.1")
  %"is_not_null" = icmp ne i8* %"calltmp", null
  %"opt_flag" = insertvalue {i1, i8*} undef, i1 %"is_not_null", 0
  %"opt_val" = insertvalue {i1, i8*} %"opt_flag", i8* %"calltmp", 1
  %"is_some" = extractvalue {i1, i8*} %"opt_val", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
ifcont:
  %"iftmp" = phi  %"Vector_String" [%".8", %"then"], [%"if_let_tmp", %"if_let_merge"]
  ret %"Vector_String" %"iftmp"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %"opt_val", 1
  %"raw_ptr" = alloca i8*
  store i8* %"unwrapped", i8** %"raw_ptr"
  %"raw_ptr.1" = load i8*, i8** %"raw_ptr"
  %"ptrcast" = bitcast i8* %"raw_ptr.1" to i8**
  %"typed_ptr" = alloca i8**
  store i8** %"ptrcast", i8*** %"typed_ptr"
  %"typed_ptr.1" = load i8**, i8*** %"typed_ptr"
  %"capacity.4" = load i64, i64* %"capacity.1"
  %".13" = insertvalue {i1, i8**} undef, i1 1, 0
  %".14" = insertvalue {i1, i8**} %".13", i8** %"typed_ptr.1", 1
  %".15" = insertvalue %"Vector_String" undef, {i1, i8**} %".14", 0
  %".16" = insertvalue %"Vector_String" %".15", i64 0, 1
  %".17" = insertvalue %"Vector_String" %".16", i64 %"capacity.4", 2
  store %"Vector_String" %".17", %"Vector_String"* %"if_let_result"
  br label %"if_let_merge"
if_let_else:
  %".18" = insertvalue {i1, i8**} undef, i1 0, 0
  %".19" = insertvalue %"Vector_String" undef, {i1, i8**} %".18", 0
  %".20" = insertvalue %"Vector_String" %".19", i64 0, 1
  %".21" = insertvalue %"Vector_String" %".20", i64 0, 2
  store %"Vector_String" %".21", %"Vector_String"* %"if_let_result"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp" = load %"Vector_String", %"Vector_String"* %"if_let_result"
  br label %"ifcont"
}

define i64 @"Vector_String_len"(%"Vector_String" %"self")
{
entry:
  %"self.1" = alloca %"Vector_String"
  store %"Vector_String" %"self", %"Vector_String"* %"self.1"
  %"self.2" = load %"Vector_String", %"Vector_String"* %"self.1"
  %".4" = extractvalue %"Vector_String" %"self.2", 1
  ret i64 %".4"
}

define i1 @"Vector_String_is_empty"(%"Vector_String" %"self")
{
entry:
  %"self.1" = alloca %"Vector_String"
  store %"Vector_String" %"self", %"Vector_String"* %"self.1"
  %"self.2" = load %"Vector_String", %"Vector_String"* %"self.1"
  %".4" = extractvalue %"Vector_String" %"self.2", 1
  %"eqtmp" = icmp eq i64 %".4", 0
  ret i1 %"eqtmp"
}

define {i1, i8*} @"Vector_String_get"(%"Vector_String" %"self", i64 %"index")
{
entry:
  %"if_let_result" = alloca {i1, i8*}
  %"self.1" = alloca %"Vector_String"
  store %"Vector_String" %"self", %"Vector_String"* %"self.1"
  %"index.1" = alloca i64
  store i64 %"index", i64* %"index.1"
  %"index.2" = load i64, i64* %"index.1"
  %"lttmp" = icmp slt i64 %"index.2", 0
  br i1 %"lttmp", label %"or_merge", label %"or_right"
or_right:
  %"index.3" = load i64, i64* %"index.1"
  %"self.2" = load %"Vector_String", %"Vector_String"* %"self.1"
  %".7" = extractvalue %"Vector_String" %"self.2", 1
  %"getmp" = icmp sge i64 %"index.3", %".7"
  br label %"or_merge"
or_merge:
  %"or_result" = phi  i1 [1, %"entry"], [%"getmp", %"or_right"]
  br i1 %"or_result", label %"then", label %"else"
then:
  %".10" = insertvalue {i1, i8*} undef, i1 0, 0
  br label %"ifcont"
else:
  %"self.3" = load %"Vector_String", %"Vector_String"* %"self.1"
  %".11" = extractvalue %"Vector_String" %"self.3", 0
  %"is_some" = extractvalue {i1, i8**} %".11", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
ifcont:
  %"iftmp" = phi  {i1, i8*} [%".10", %"then"], [%"if_let_tmp", %"if_let_merge"]
  ret {i1, i8*} %"iftmp"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8**} %".11", 1
  %"buf" = alloca i8**
  store i8** %"unwrapped", i8*** %"buf"
  %"buf.1" = load i8**, i8*** %"buf"
  %"index.4" = load i64, i64* %"index.1"
  %"ptr_idx" = getelementptr i8*, i8** %"buf.1", i64 %"index.4"
  %"ptr_elem" = load i8*, i8** %"ptr_idx"
  %".15" = insertvalue {i1, i8*} undef, i1 1, 0
  %"some_then" = insertvalue {i1, i8*} %".15", i8* %"ptr_elem", 1
  store {i1, i8*} %"some_then", {i1, i8*}* %"if_let_result"
  br label %"if_let_merge"
if_let_else:
  %".14" = insertvalue {i1, i8*} undef, i1 0, 0
  store {i1, i8*} %".14", {i1, i8*}* %"if_let_result"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp" = load {i1, i8*}, {i1, i8*}* %"if_let_result"
  br label %"ifcont"
}

define void @"Vector_String_set"(%"Vector_String"* %"self", i64 %"index", i8* %"value")
{
entry:
  %"index.1" = alloca i64
  store i64 %"index", i64* %"index.1"
  %"value.1" = alloca i8*
  store i8* %"value", i8** %"value.1"
  %"index.2" = load i64, i64* %"index.1"
  %"getmp" = icmp sge i64 %"index.2", 0
  br i1 %"getmp", label %"and_right", label %"and_merge"
and_right:
  %"index.3" = load i64, i64* %"index.1"
  %"self.1" = load %"Vector_String", %"Vector_String"* %"self"
  %".8" = extractvalue %"Vector_String" %"self.1", 1
  %"lttmp" = icmp slt i64 %"index.3", %".8"
  br label %"and_merge"
and_merge:
  %"and_result" = phi  i1 [0, %"entry"], [%"lttmp", %"and_right"]
  br i1 %"and_result", label %"then", label %"else"
then:
  %"self.2" = load %"Vector_String", %"Vector_String"* %"self"
  %".11" = extractvalue %"Vector_String" %"self.2", 0
  %"is_some" = extractvalue {i1, i8**} %".11", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
else:
  br label %"ifcont"
ifcont:
  ret void
if_let_then:
  %"unwrapped" = extractvalue {i1, i8**} %".11", 1
  %"buf" = alloca i8**
  store i8** %"unwrapped", i8*** %"buf"
  %"value.2" = load i8*, i8** %"value.1"
  %"index.4" = load i64, i64* %"index.1"
  %"container" = load i8**, i8*** %"buf"
  %"ptr_elem" = getelementptr i8*, i8** %"container", i64 %"index.4"
  store i8* %"value.2", i8** %"ptr_elem"
  br label %"if_let_merge"
if_let_else:
  br label %"if_let_merge"
if_let_merge:
  br label %"ifcont"
}

define void @"Vector_String_push"(%"Vector_String"* %"self", i8* %"value")
{
entry:
  %"value.1" = alloca i8*
  store i8* %"value", i8** %"value.1"
  %"self.1" = load %"Vector_String", %"Vector_String"* %"self"
  %".5" = extractvalue %"Vector_String" %"self.1", 1
  %"self.2" = load %"Vector_String", %"Vector_String"* %"self"
  %".6" = extractvalue %"Vector_String" %"self.2", 2
  %"getmp" = icmp sge i64 %".5", %".6"
  br i1 %"getmp", label %"then", label %"else"
then:
  %"self.3" = load %"Vector_String", %"Vector_String"* %"self"
  call void @"Vector_String_grow"(%"Vector_String"* %"self")
  br label %"ifcont"
else:
  br label %"ifcont"
ifcont:
  %"self.4" = load %"Vector_String", %"Vector_String"* %"self"
  %".10" = extractvalue %"Vector_String" %"self.4", 0
  %"is_some" = extractvalue {i1, i8**} %".10", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8**} %".10", 1
  %"buf" = alloca i8**
  store i8** %"unwrapped", i8*** %"buf"
  %"value.2" = load i8*, i8** %"value.1"
  %"self.5" = load %"Vector_String", %"Vector_String"* %"self"
  %".13" = extractvalue %"Vector_String" %"self.5", 1
  %"container" = load i8**, i8*** %"buf"
  %"ptr_elem" = getelementptr i8*, i8** %"container", i64 %".13"
  store i8* %"value.2", i8** %"ptr_elem"
  %"self.6" = load %"Vector_String", %"Vector_String"* %"self"
  %".15" = extractvalue %"Vector_String" %"self.6", 1
  %"addtmp" = add i64 %".15", 1
  %"length_ptr" = getelementptr %"Vector_String", %"Vector_String"* %"self", i32 0, i32 1
  store i64 %"addtmp", i64* %"length_ptr"
  br label %"if_let_merge"
if_let_else:
  br label %"if_let_merge"
if_let_merge:
  ret void
}

define {i1, i8*} @"Vector_String_pop"(%"Vector_String"* %"self")
{
entry:
  %"if_let_result" = alloca {i1, i8*}
  %"self.1" = load %"Vector_String", %"Vector_String"* %"self"
  %".3" = extractvalue %"Vector_String" %"self.1", 1
  %"eqtmp" = icmp eq i64 %".3", 0
  br i1 %"eqtmp", label %"then", label %"else"
then:
  %".5" = insertvalue {i1, i8*} undef, i1 0, 0
  br label %"ifcont"
else:
  %"self.2" = load %"Vector_String", %"Vector_String"* %"self"
  %".6" = extractvalue %"Vector_String" %"self.2", 1
  %"subtmp" = sub i64 %".6", 1
  %"length_ptr" = getelementptr %"Vector_String", %"Vector_String"* %"self", i32 0, i32 1
  store i64 %"subtmp", i64* %"length_ptr"
  %"self.3" = load %"Vector_String", %"Vector_String"* %"self"
  %".8" = extractvalue %"Vector_String" %"self.3", 0
  %"is_some" = extractvalue {i1, i8**} %".8", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
ifcont:
  %"iftmp" = phi  {i1, i8*} [%".5", %"then"], [%"if_let_tmp", %"if_let_merge"]
  ret {i1, i8*} %"iftmp"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8**} %".8", 1
  %"buf" = alloca i8**
  store i8** %"unwrapped", i8*** %"buf"
  %"buf.1" = load i8**, i8*** %"buf"
  %"self.4" = load %"Vector_String", %"Vector_String"* %"self"
  %".11" = extractvalue %"Vector_String" %"self.4", 1
  %"ptr_idx" = getelementptr i8*, i8** %"buf.1", i64 %".11"
  %"ptr_elem" = load i8*, i8** %"ptr_idx"
  %".13" = insertvalue {i1, i8*} undef, i1 1, 0
  %"some_then" = insertvalue {i1, i8*} %".13", i8* %"ptr_elem", 1
  store {i1, i8*} %"some_then", {i1, i8*}* %"if_let_result"
  br label %"if_let_merge"
if_let_else:
  %".12" = insertvalue {i1, i8*} undef, i1 0, 0
  store {i1, i8*} %".12", {i1, i8*}* %"if_let_result"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp" = load {i1, i8*}, {i1, i8*}* %"if_let_result"
  br label %"ifcont"
}

define void @"Vector_String_clear"(%"Vector_String"* %"self")
{
entry:
  %"length_ptr" = getelementptr %"Vector_String", %"Vector_String"* %"self", i32 0, i32 1
  store i64 0, i64* %"length_ptr"
  ret void
}

define void @"Vector_String_grow"(%"Vector_String"* %"self")
{
entry:
  %"self.1" = load %"Vector_String", %"Vector_String"* %"self"
  %".3" = extractvalue %"Vector_String" %"self.1", 2
  %"eqtmp" = icmp eq i64 %".3", 0
  br i1 %"eqtmp", label %"then", label %"else"
then:
  br label %"ifcont"
else:
  %"self.2" = load %"Vector_String", %"Vector_String"* %"self"
  %".5" = extractvalue %"Vector_String" %"self.2", 2
  %"multmp" = mul i64 %".5", 2
  br label %"ifcont"
ifcont:
  %"iftmp" = phi  i64 [4, %"then"], [%"multmp", %"else"]
  %"new_capacity" = alloca i64
  store i64 %"iftmp", i64* %"new_capacity"
  %"new_capacity.1" = load i64, i64* %"new_capacity"
  %"multmp.1" = mul i64 %"new_capacity.1", 8
  %"new_byte_size" = alloca i64
  store i64 %"multmp.1", i64* %"new_byte_size"
  %"self.3" = load %"Vector_String", %"Vector_String"* %"self"
  %".10" = extractvalue %"Vector_String" %"self.3", 0
  %"is_some" = extractvalue {i1, i8**} %".10", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8**} %".10", 1
  %"buf" = alloca i8**
  store i8** %"unwrapped", i8*** %"buf"
  %"buf.1" = load i8**, i8*** %"buf"
  %"ptrcast" = bitcast i8** %"buf.1" to i8*
  %"raw_ptr" = alloca i8*
  store i8* %"ptrcast", i8** %"raw_ptr"
  %"raw_ptr.1" = load i8*, i8** %"raw_ptr"
  %"new_byte_size.1" = load i64, i64* %"new_byte_size"
  %"calltmp" = call i8* @"realloc"(i8* %"raw_ptr.1", i64 %"new_byte_size.1")
  %"is_not_null" = icmp ne i8* %"calltmp", null
  %"opt_flag" = insertvalue {i1, i8*} undef, i1 %"is_not_null", 0
  %"opt_val" = insertvalue {i1, i8*} %"opt_flag", i8* %"calltmp", 1
  %"is_some.1" = extractvalue {i1, i8*} %"opt_val", 0
  br i1 %"is_some.1", label %"if_let_then.1", label %"if_let_else.1"
if_let_else:
  %"new_byte_size.2" = load i64, i64* %"new_byte_size"
  %"calltmp.1" = call i8* @"malloc"(i64 %"new_byte_size.2")
  %"is_not_null.1" = icmp ne i8* %"calltmp.1", null
  %"opt_flag.1" = insertvalue {i1, i8*} undef, i1 %"is_not_null.1", 0
  %"opt_val.1" = insertvalue {i1, i8*} %"opt_flag.1", i8* %"calltmp.1", 1
  %"is_some.2" = extractvalue {i1, i8*} %"opt_val.1", 0
  br i1 %"is_some.2", label %"if_let_then.2", label %"if_let_else.2"
if_let_merge:
  ret void
if_let_then.1:
  %"unwrapped.1" = extractvalue {i1, i8*} %"opt_val", 1
  %"new_raw" = alloca i8*
  store i8* %"unwrapped.1", i8** %"new_raw"
  %"new_raw.1" = load i8*, i8** %"new_raw"
  %"ptrcast.1" = bitcast i8* %"new_raw.1" to i8**
  %"buffer_ptr" = getelementptr %"Vector_String", %"Vector_String"* %"self", i32 0, i32 0
  %".16" = insertvalue {i1, i8**} undef, i1 1, 0
  %".17" = insertvalue {i1, i8**} %".16", i8** %"ptrcast.1", 1
  store {i1, i8**} %".17", {i1, i8**}* %"buffer_ptr"
  %"new_capacity.2" = load i64, i64* %"new_capacity"
  %"capacity_ptr" = getelementptr %"Vector_String", %"Vector_String"* %"self", i32 0, i32 2
  store i64 %"new_capacity.2", i64* %"capacity_ptr"
  br label %"if_let_merge.1"
if_let_else.1:
  br label %"if_let_merge.1"
if_let_merge.1:
  br label %"if_let_merge"
if_let_then.2:
  %"unwrapped.2" = extractvalue {i1, i8*} %"opt_val.1", 1
  %"raw_ptr.2" = alloca i8*
  store i8* %"unwrapped.2", i8** %"raw_ptr.2"
  %"raw_ptr.3" = load i8*, i8** %"raw_ptr.2"
  %"ptrcast.2" = bitcast i8* %"raw_ptr.3" to i8**
  %"buffer_ptr.1" = getelementptr %"Vector_String", %"Vector_String"* %"self", i32 0, i32 0
  %".24" = insertvalue {i1, i8**} undef, i1 1, 0
  %".25" = insertvalue {i1, i8**} %".24", i8** %"ptrcast.2", 1
  store {i1, i8**} %".25", {i1, i8**}* %"buffer_ptr.1"
  %"new_capacity.3" = load i64, i64* %"new_capacity"
  %"capacity_ptr.1" = getelementptr %"Vector_String", %"Vector_String"* %"self", i32 0, i32 2
  store i64 %"new_capacity.3", i64* %"capacity_ptr.1"
  br label %"if_let_merge.2"
if_let_else.2:
  br label %"if_let_merge.2"
if_let_merge.2:
  br label %"if_let_merge"
}

define {i1, i8*} @"VectorIterator_String_next"(%"VectorIterator_String"* %"self")
{
entry:
  %"if_let_result" = alloca {i1, i8*}
  %"self.1" = load %"VectorIterator_String", %"VectorIterator_String"* %"self"
  %".3" = extractvalue %"VectorIterator_String" %"self.1", 2
  %"self.2" = load %"VectorIterator_String", %"VectorIterator_String"* %"self"
  %".4" = extractvalue %"VectorIterator_String" %"self.2", 1
  %"lttmp" = icmp slt i64 %".3", %".4"
  br i1 %"lttmp", label %"then", label %"else"
then:
  %"self.3" = load %"VectorIterator_String", %"VectorIterator_String"* %"self"
  %".6" = extractvalue %"VectorIterator_String" %"self.3", 2
  %"idx" = alloca i64
  store i64 %".6", i64* %"idx"
  %"self.4" = load %"VectorIterator_String", %"VectorIterator_String"* %"self"
  %".8" = extractvalue %"VectorIterator_String" %"self.4", 2
  %"addtmp" = add i64 %".8", 1
  %"index_ptr" = getelementptr %"VectorIterator_String", %"VectorIterator_String"* %"self", i32 0, i32 2
  store i64 %"addtmp", i64* %"index_ptr"
  %"self.5" = load %"VectorIterator_String", %"VectorIterator_String"* %"self"
  %".10" = extractvalue %"VectorIterator_String" %"self.5", 0
  %"is_some" = extractvalue {i1, i8**} %".10", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
else:
  %".19" = insertvalue {i1, i8*} undef, i1 0, 0
  br label %"ifcont"
ifcont:
  %"iftmp" = phi  {i1, i8*} [%"if_let_tmp", %"if_let_merge"], [%".19", %"else"]
  ret {i1, i8*} %"iftmp"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8**} %".10", 1
  %"buf" = alloca i8**
  store i8** %"unwrapped", i8*** %"buf"
  %"buf.1" = load i8**, i8*** %"buf"
  %"idx.1" = load i64, i64* %"idx"
  %"ptr_idx" = getelementptr i8*, i8** %"buf.1", i64 %"idx.1"
  %"ptr_elem" = load i8*, i8** %"ptr_idx"
  %".14" = insertvalue {i1, i8*} undef, i1 1, 0
  %"some_then" = insertvalue {i1, i8*} %".14", i8* %"ptr_elem", 1
  store {i1, i8*} %"some_then", {i1, i8*}* %"if_let_result"
  br label %"if_let_merge"
if_let_else:
  %".13" = insertvalue {i1, i8*} undef, i1 0, 0
  store {i1, i8*} %".13", {i1, i8*}* %"if_let_result"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp" = load {i1, i8*}, {i1, i8*}* %"if_let_result"
  br label %"ifcont"
}

define %"VectorIterator_String" @"Vector_String_iter"(%"Vector_String" %"self")
{
entry:
  %"self.1" = alloca %"Vector_String"
  store %"Vector_String" %"self", %"Vector_String"* %"self.1"
  %"self.2" = load %"Vector_String", %"Vector_String"* %"self.1"
  %".4" = extractvalue %"Vector_String" %"self.2", 0
  %"self.3" = load %"Vector_String", %"Vector_String"* %"self.1"
  %".5" = extractvalue %"Vector_String" %"self.3", 1
  %".6" = insertvalue %"VectorIterator_String" undef, {i1, i8**} %".4", 0
  %".7" = insertvalue %"VectorIterator_String" %".6", i64 %".5", 1
  %".8" = insertvalue %"VectorIterator_String" %".7", i64 0, 2
  ret %"VectorIterator_String" %".8"
}

define void @"Vector_String_deinit"(%"Vector_String"* %"self")
{
entry:
  %"self.1" = load %"Vector_String", %"Vector_String"* %"self"
  %".3" = extractvalue %"Vector_String" %"self.1", 0
  %"is_some" = extractvalue {i1, i8**} %".3", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8**} %".3", 1
  %"buf" = alloca i8**
  store i8** %"unwrapped", i8*** %"buf"
  %"buf.1" = load i8**, i8*** %"buf"
  %"ptrcast" = bitcast i8** %"buf.1" to i8*
  %"raw_ptr" = alloca i8*
  store i8* %"ptrcast", i8** %"raw_ptr"
  %"raw_ptr.1" = load i8*, i8** %"raw_ptr"
  call void @"free"(i8* %"raw_ptr.1")
  br label %"if_let_merge"
if_let_else:
  br label %"if_let_merge"
if_let_merge:
  ret void
}

define i8* @"Vector_String_join"(%"Vector_String" %"self", i8* %"separator")
{
entry:
  %"if_let_result.1" = alloca i8*
  %"if_let_result" = alloca i8*
  %"self.1" = alloca %"Vector_String"
  store %"Vector_String" %"self", %"Vector_String"* %"self.1"
  %"separator.1" = alloca i8*
  store i8* %"separator", i8** %"separator.1"
  %"self.2" = load %"Vector_String", %"Vector_String"* %"self.1"
  %"methodcall" = call i64 @"Vector_String_len"(%"Vector_String" %"self.2")
  %"count" = alloca i64
  store i64 %"methodcall", i64* %"count"
  %"count.1" = load i64, i64* %"count"
  %"eqtmp" = icmp eq i64 %"count.1", 0
  br i1 %"eqtmp", label %"then", label %"else"
then:
  %".8" = getelementptr inbounds [1 x i8], [1 x i8]* @".str.5", i32 0, i32 0
  br label %"ifcont"
else:
  %"count.2" = load i64, i64* %"count"
  %"eqtmp.1" = icmp eq i64 %"count.2", 1
  br i1 %"eqtmp.1", label %"then.1", label %"else.1"
ifcont:
  %"iftmp.1" = phi  i8* [%".8", %"then"], [%"iftmp", %"ifcont.1"]
  ret i8* %"iftmp.1"
then.1:
  %"self.3" = load %"Vector_String", %"Vector_String"* %"self.1"
  %"methodcall.1" = call {i1, i8*} @"Vector_String_get"(%"Vector_String" %"self.3", i64 0)
  %"is_some" = extractvalue {i1, i8*} %"methodcall.1", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
else.1:
  %"separator.2" = load i8*, i8** %"separator.1"
  %"methodcall.2" = call i64 @"String_len"(i8* %"separator.2")
  %"sep_len" = alloca i64
  store i64 %"methodcall.2", i64* %"sep_len"
  %"total_len" = alloca i64
  store i64 0, i64* %"total_len"
  %"i" = alloca i64
  store i64 0, i64* %"i"
  br label %"while.cond"
ifcont.1:
  %"iftmp" = phi  i8* [%"if_let_tmp", %"if_let_merge"], [%"if_let_tmp.1", %"if_let_merge.2"]
  br label %"ifcont"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %"methodcall.1", 1
  %"first" = alloca i8*
  store i8* %"unwrapped", i8** %"first"
  %"first.1" = load i8*, i8** %"first"
  store i8* %"first.1", i8** %"if_let_result"
  br label %"if_let_merge"
if_let_else:
  %".12" = getelementptr inbounds [1 x i8], [1 x i8]* @".str.5", i32 0, i32 0
  store i8* %".12", i8** %"if_let_result"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp" = load i8*, i8** %"if_let_result"
  br label %"ifcont.1"
while.cond:
  %"i.1" = load i64, i64* %"i"
  %"count.3" = load i64, i64* %"count"
  %"lttmp" = icmp slt i64 %"i.1", %"count.3"
  br i1 %"lttmp", label %"while.body", label %"while.end"
while.body:
  %"self.4" = load %"Vector_String", %"Vector_String"* %"self.1"
  %"i.2" = load i64, i64* %"i"
  %"methodcall.3" = call {i1, i8*} @"Vector_String_get"(%"Vector_String" %"self.4", i64 %"i.2")
  %"is_some.1" = extractvalue {i1, i8*} %"methodcall.3", 0
  br i1 %"is_some.1", label %"if_let_then.1", label %"if_let_else.1"
while.end:
  %"total_len.2" = load i64, i64* %"total_len"
  %"sep_len.1" = load i64, i64* %"sep_len"
  %"count.4" = load i64, i64* %"count"
  %"subtmp" = sub i64 %"count.4", 1
  %"multmp" = mul i64 %"sep_len.1", %"subtmp"
  %"addtmp.2" = add i64 %"total_len.2", %"multmp"
  store i64 %"addtmp.2", i64* %"total_len"
  %"total_len.3" = load i64, i64* %"total_len"
  %"addtmp.3" = add i64 %"total_len.3", 1
  %"calltmp" = call i8* @"malloc"(i64 %"addtmp.3")
  %"is_not_null" = icmp ne i8* %"calltmp", null
  %"opt_flag" = insertvalue {i1, i8*} undef, i1 %"is_not_null", 0
  %"opt_val" = insertvalue {i1, i8*} %"opt_flag", i8* %"calltmp", 1
  %"is_some.2" = extractvalue {i1, i8*} %"opt_val", 0
  br i1 %"is_some.2", label %"if_let_then.2", label %"if_let_else.2"
if_let_then.1:
  %"unwrapped.1" = extractvalue {i1, i8*} %"methodcall.3", 1
  %"s" = alloca i8*
  store i8* %"unwrapped.1", i8** %"s"
  %"total_len.1" = load i64, i64* %"total_len"
  %"s.1" = load i8*, i8** %"s"
  %"methodcall.4" = call i64 @"String_len"(i8* %"s.1")
  %"addtmp" = add i64 %"total_len.1", %"methodcall.4"
  store i64 %"addtmp", i64* %"total_len"
  br label %"if_let_merge.1"
if_let_else.1:
  br label %"if_let_merge.1"
if_let_merge.1:
  %"i.3" = load i64, i64* %"i"
  %"addtmp.1" = add i64 %"i.3", 1
  store i64 %"addtmp.1", i64* %"i"
  br label %"while.cond"
if_let_then.2:
  %"unwrapped.2" = extractvalue {i1, i8*} %"opt_val", 1
  %"buf" = alloca i8*
  store i8* %"unwrapped.2", i8** %"buf"
  %"pos" = alloca i64
  store i64 0, i64* %"pos"
  %"idx" = alloca i64
  store i64 0, i64* %"idx"
  br label %"while.cond.1"
if_let_else.2:
  %".61" = getelementptr inbounds [1 x i8], [1 x i8]* @".str.5", i32 0, i32 0
  store i8* %".61", i8** %"if_let_result.1"
  br label %"if_let_merge.2"
if_let_merge.2:
  %"if_let_tmp.1" = load i8*, i8** %"if_let_result.1"
  br label %"ifcont.1"
while.cond.1:
  %"idx.1" = load i64, i64* %"idx"
  %"count.5" = load i64, i64* %"count"
  %"lttmp.1" = icmp slt i64 %"idx.1", %"count.5"
  br i1 %"lttmp.1", label %"while.body.1", label %"while.end.1"
while.body.1:
  %"idx.2" = load i64, i64* %"idx"
  %"gttmp" = icmp sgt i64 %"idx.2", 0
  br i1 %"gttmp", label %"then.2", label %"else.2"
while.end.1:
  %"trunc" = trunc i64 0 to i8
  %"total_len.4" = load i64, i64* %"total_len"
  %"container.2" = load i8*, i8** %"buf"
  %"ptr_elem.2" = getelementptr i8, i8* %"container.2", i64 %"total_len.4"
  store i8 %"trunc", i8* %"ptr_elem.2"
  %"buf.1" = load i8*, i8** %"buf"
  store i8* %"buf.1", i8** %"if_let_result.1"
  br label %"if_let_merge.2"
then.2:
  %"k" = alloca i64
  store i64 0, i64* %"k"
  br label %"while.cond.2"
else.2:
  br label %"ifcont.2"
ifcont.2:
  %"self.5" = load %"Vector_String", %"Vector_String"* %"self.1"
  %"idx.3" = load i64, i64* %"idx"
  %"methodcall.6" = call {i1, i8*} @"Vector_String_get"(%"Vector_String" %"self.5", i64 %"idx.3")
  %"is_some.3" = extractvalue {i1, i8*} %"methodcall.6", 0
  br i1 %"is_some.3", label %"if_let_then.3", label %"if_let_else.3"
while.cond.2:
  %"k.1" = load i64, i64* %"k"
  %"sep_len.2" = load i64, i64* %"sep_len"
  %"lttmp.2" = icmp slt i64 %"k.1", %"sep_len.2"
  br i1 %"lttmp.2", label %"while.body.2", label %"while.end.2"
while.body.2:
  %"separator.3" = load i8*, i8** %"separator.1"
  %"k.2" = load i64, i64* %"k"
  %"methodcall.5" = call i8 @"String_byte_at"(i8* %"separator.3", i64 %"k.2")
  %"pos.1" = load i64, i64* %"pos"
  %"container" = load i8*, i8** %"buf"
  %"ptr_elem" = getelementptr i8, i8* %"container", i64 %"pos.1"
  store i8 %"methodcall.5", i8* %"ptr_elem"
  %"pos.2" = load i64, i64* %"pos"
  %"addtmp.4" = add i64 %"pos.2", 1
  store i64 %"addtmp.4", i64* %"pos"
  %"k.3" = load i64, i64* %"k"
  %"addtmp.5" = add i64 %"k.3", 1
  store i64 %"addtmp.5", i64* %"k"
  br label %"while.cond.2"
while.end.2:
  br label %"ifcont.2"
if_let_then.3:
  %"unwrapped.3" = extractvalue {i1, i8*} %"methodcall.6", 1
  %"s.2" = alloca i8*
  store i8* %"unwrapped.3", i8** %"s.2"
  %"s.3" = load i8*, i8** %"s.2"
  %"methodcall.7" = call i64 @"String_len"(i8* %"s.3")
  %"s_len" = alloca i64
  store i64 %"methodcall.7", i64* %"s_len"
  %"j" = alloca i64
  store i64 0, i64* %"j"
  br label %"while.cond.3"
if_let_else.3:
  br label %"if_let_merge.3"
if_let_merge.3:
  %"idx.4" = load i64, i64* %"idx"
  %"addtmp.8" = add i64 %"idx.4", 1
  store i64 %"addtmp.8", i64* %"idx"
  br label %"while.cond.1"
while.cond.3:
  %"j.1" = load i64, i64* %"j"
  %"s_len.1" = load i64, i64* %"s_len"
  %"lttmp.3" = icmp slt i64 %"j.1", %"s_len.1"
  br i1 %"lttmp.3", label %"while.body.3", label %"while.end.3"
while.body.3:
  %"s.4" = load i8*, i8** %"s.2"
  %"j.2" = load i64, i64* %"j"
  %"methodcall.8" = call i8 @"String_byte_at"(i8* %"s.4", i64 %"j.2")
  %"pos.3" = load i64, i64* %"pos"
  %"container.1" = load i8*, i8** %"buf"
  %"ptr_elem.1" = getelementptr i8, i8* %"container.1", i64 %"pos.3"
  store i8 %"methodcall.8", i8* %"ptr_elem.1"
  %"pos.4" = load i64, i64* %"pos"
  %"addtmp.6" = add i64 %"pos.4", 1
  store i64 %"addtmp.6", i64* %"pos"
  %"j.3" = load i64, i64* %"j"
  %"addtmp.7" = add i64 %"j.3", 1
  store i64 %"addtmp.7", i64* %"j"
  br label %"while.cond.3"
while.end.3:
  br label %"if_let_merge.3"
}

define %"Vector_String" @"Env_args"()
{
entry:
  %".2" = call %"Vector_String" @"Vector_String_init_"()
  %"result" = alloca %"Vector_String"
  store %"Vector_String" %".2", %"Vector_String"* %"result"
  %"static_methodcall" = call i64 @"Env_argc"()
  %"argc" = alloca i64
  store i64 %"static_methodcall", i64* %"argc"
  %"i" = alloca i64
  store i64 0, i64* %"i"
  br label %"while.cond"
while.cond:
  %"i.1" = load i64, i64* %"i"
  %"argc.1" = load i64, i64* %"argc"
  %"lttmp" = icmp slt i64 %"i.1", %"argc.1"
  br i1 %"lttmp", label %"while.body", label %"while.end"
while.body:
  %"i.2" = load i64, i64* %"i"
  %"static_methodcall.1" = call {i1, i8*} @"Env_arg"(i64 %"i.2")
  %"is_some" = extractvalue {i1, i8*} %"static_methodcall.1", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
while.end:
  %"result_moved" = load %"Vector_String", %"Vector_String"* %"result"
  ret %"Vector_String" %"result_moved"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %"static_methodcall.1", 1
  %"arg" = alloca i8*
  store i8* %"unwrapped", i8** %"arg"
  %"result.1" = load %"Vector_String", %"Vector_String"* %"result"
  %"arg.1" = load i8*, i8** %"arg"
  call void @"Vector_String_push"(%"Vector_String"* %"result", i8* %"arg.1")
  br label %"if_let_merge"
if_let_else:
  br label %"if_let_merge"
if_let_merge:
  %"i.3" = load i64, i64* %"i"
  %"addtmp" = add i64 %"i.3", 1
  store i64 %"addtmp", i64* %"i"
  br label %"while.cond"
}

define {i1, i8*} @"Env_get"(i8* %"name")
{
entry:
  %"if_let_result" = alloca {i1, i8*}
  %"name.1" = alloca i8*
  store i8* %"name", i8** %"name.1"
  %"name.2" = load i8*, i8** %"name.1"
  %"name_ptr" = alloca i8*
  store i8* %"name.2", i8** %"name_ptr"
  %"name_ptr.1" = load i8*, i8** %"name_ptr"
  %"calltmp" = call i8* @"getenv"(i8* %"name_ptr.1")
  %"is_not_null" = icmp ne i8* %"calltmp", null
  %"opt_flag" = insertvalue {i1, i8*} undef, i1 %"is_not_null", 0
  %"opt_val" = insertvalue {i1, i8*} %"opt_flag", i8* %"calltmp", 1
  %"is_some" = extractvalue {i1, i8*} %"opt_val", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %"opt_val", 1
  %"value_ptr" = alloca i8*
  store i8* %"unwrapped", i8** %"value_ptr"
  %"value_ptr.1" = load i8*, i8** %"value_ptr"
  %".8" = insertvalue {i1, i8*} undef, i1 1, 0
  %"some_then" = insertvalue {i1, i8*} %".8", i8* %"value_ptr.1", 1
  store {i1, i8*} %"some_then", {i1, i8*}* %"if_let_result"
  br label %"if_let_merge"
if_let_else:
  %".7" = insertvalue {i1, i8*} undef, i1 0, 0
  store {i1, i8*} %".7", {i1, i8*}* %"if_let_result"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp" = load {i1, i8*}, {i1, i8*}* %"if_let_result"
  ret {i1, i8*} %"if_let_tmp"
}

define i1 @"Env_set"(i8* %"name", i8* %"value", i1 %"overwrite")
{
entry:
  %"name.1" = alloca i8*
  store i8* %"name", i8** %"name.1"
  %"value.1" = alloca i8*
  store i8* %"value", i8** %"value.1"
  %"overwrite.1" = alloca i1
  store i1 %"overwrite", i1* %"overwrite.1"
  %"name.2" = load i8*, i8** %"name.1"
  %"name_ptr" = alloca i8*
  store i8* %"name.2", i8** %"name_ptr"
  %"value.2" = load i8*, i8** %"value.1"
  %"value_ptr" = alloca i8*
  store i8* %"value.2", i8** %"value_ptr"
  %"overwrite.2" = load i1, i1* %"overwrite.1"
  br i1 %"overwrite.2", label %"then", label %"else"
then:
  %"trunc" = trunc i64 1 to i32
  br label %"ifcont"
else:
  %"trunc.1" = trunc i64 0 to i32
  br label %"ifcont"
ifcont:
  %"iftmp" = phi  i32 [%"trunc", %"then"], [%"trunc.1", %"else"]
  %"overwrite_flag" = alloca i32
  store i32 %"iftmp", i32* %"overwrite_flag"
  %"name_ptr.1" = load i8*, i8** %"name_ptr"
  %"value_ptr.1" = load i8*, i8** %"value_ptr"
  %"overwrite_flag.1" = load i32, i32* %"overwrite_flag"
  %"calltmp" = call i32 @"setenv"(i8* %"name_ptr.1", i8* %"value_ptr.1", i32 %"overwrite_flag.1")
  %"trunc.2" = trunc i64 0 to i32
  %"eqtmp" = icmp eq i32 %"calltmp", %"trunc.2"
  ret i1 %"eqtmp"
}

define i1 @"Env_unset"(i8* %"name")
{
entry:
  %"name.1" = alloca i8*
  store i8* %"name", i8** %"name.1"
  %"name.2" = load i8*, i8** %"name.1"
  %"name_ptr" = alloca i8*
  store i8* %"name.2", i8** %"name_ptr"
  %"name_ptr.1" = load i8*, i8** %"name_ptr"
  %"calltmp" = call i32 @"unsetenv"(i8* %"name_ptr.1")
  %"trunc" = trunc i64 0 to i32
  %"eqtmp" = icmp eq i32 %"calltmp", %"trunc"
  ret i1 %"eqtmp"
}

define i1 @"Env_contains"(i8* %"name")
{
entry:
  %"if_let_result" = alloca i1
  %"name.1" = alloca i8*
  store i8* %"name", i8** %"name.1"
  %"name.2" = load i8*, i8** %"name.1"
  %"name_ptr" = alloca i8*
  store i8* %"name.2", i8** %"name_ptr"
  %"name_ptr.1" = load i8*, i8** %"name_ptr"
  %"calltmp" = call i8* @"getenv"(i8* %"name_ptr.1")
  %"is_not_null" = icmp ne i8* %"calltmp", null
  %"opt_flag" = insertvalue {i1, i8*} undef, i1 %"is_not_null", 0
  %"opt_val" = insertvalue {i1, i8*} %"opt_flag", i8* %"calltmp", 1
  %"is_some" = extractvalue {i1, i8*} %"opt_val", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %"opt_val", 1
  %"_" = alloca i8*
  store i8* %"unwrapped", i8** %"_"
  store i1 1, i1* %"if_let_result"
  br label %"if_let_merge"
if_let_else:
  store i1 0, i1* %"if_let_result"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp" = load i1, i1* %"if_let_result"
  ret i1 %"if_let_tmp"
}

define {i1, %"Path"} @"Env_cwd"()
{
entry:
  %"static_methodcall" = call {i1, %"Path"} @"Directory_current"()
  ret {i1, %"Path"} %"static_methodcall"
}

define i1 @"Env_set_cwd"(%"Path" %"path")
{
entry:
  %"path.1" = alloca %"Path"
  store %"Path" %"path", %"Path"* %"path.1"
  %"path.2" = load %"Path", %"Path"* %"path.1"
  %"static_methodcall" = call i1 @"Directory_set_current"(%"Path" %"path.2")
  ret i1 %"static_methodcall"
}

define {i1, %"File"} @"File_open"(%"Path" %"path")
{
entry:
  %"if_result" = alloca {i1, %"File"}
  %"path.1" = alloca %"Path"
  store %"Path" %"path", %"Path"* %"path.1"
  %"path.2" = load %"Path", %"Path"* %"path.1"
  %"methodcall" = call i8* @"Path_as_str"(%"Path" %"path.2")
  %"path_ptr" = alloca i8*
  store i8* %"methodcall", i8** %"path_ptr"
  %"path_ptr.1" = load i8*, i8** %"path_ptr"
  %"trunc" = trunc i64 0 to i32
  %"trunc.1" = trunc i64 0 to i32
  %"calltmp" = call i32 (i8*, i32, ...) @"open"(i8* %"path_ptr.1", i32 %"trunc", i32 %"trunc.1")
  %"fd" = alloca i32
  store i32 %"calltmp", i32* %"fd"
  %"fd.1" = load i32, i32* %"fd"
  %"trunc.2" = trunc i64 0 to i32
  %"lttmp" = icmp slt i32 %"fd.1", %"trunc.2"
  br i1 %"lttmp", label %"then", label %"else"
then:
  %".7" = insertvalue {i1, %"File"} undef, i1 0, 0
  store {i1, %"File"} %".7", {i1, %"File"}* %"if_result"
  br label %"ifcont"
else:
  %"fd.2" = load i32, i32* %"fd"
  %".8" = insertvalue %"File" undef, i32 %"fd.2", 0
  %".11" = insertvalue {i1, %"File"} undef, i1 1, 0
  %"some_else" = insertvalue {i1, %"File"} %".11", %"File" %".8", 1
  store {i1, %"File"} %"some_else", {i1, %"File"}* %"if_result"
  br label %"ifcont"
ifcont:
  %"iftmp" = load {i1, %"File"}, {i1, %"File"}* %"if_result"
  ret {i1, %"File"} %"iftmp"
}

define {i1, %"File"} @"File_create"(%"Path" %"path")
{
entry:
  %"if_result" = alloca {i1, %"File"}
  %"path.1" = alloca %"Path"
  store %"Path" %"path", %"Path"* %"path.1"
  %"path.2" = load %"Path", %"Path"* %"path.1"
  %"methodcall" = call i8* @"Path_as_str"(%"Path" %"path.2")
  %"path_ptr" = alloca i8*
  store i8* %"methodcall", i8** %"path_ptr"
  %"path_ptr.1" = load i8*, i8** %"path_ptr"
  %"trunc" = trunc i64 577 to i32
  %"calltmp" = call i32 (i8*, i32, ...) @"open"(i8* %"path_ptr.1", i32 %"trunc", i64 420)
  %"fd" = alloca i32
  store i32 %"calltmp", i32* %"fd"
  %"fd.1" = load i32, i32* %"fd"
  %"trunc.1" = trunc i64 0 to i32
  %"lttmp" = icmp slt i32 %"fd.1", %"trunc.1"
  br i1 %"lttmp", label %"then", label %"else"
then:
  %".7" = insertvalue {i1, %"File"} undef, i1 0, 0
  store {i1, %"File"} %".7", {i1, %"File"}* %"if_result"
  br label %"ifcont"
else:
  %"fd.2" = load i32, i32* %"fd"
  %".8" = insertvalue %"File" undef, i32 %"fd.2", 0
  %".11" = insertvalue {i1, %"File"} undef, i1 1, 0
  %"some_else" = insertvalue {i1, %"File"} %".11", %"File" %".8", 1
  store {i1, %"File"} %"some_else", {i1, %"File"}* %"if_result"
  br label %"ifcont"
ifcont:
  %"iftmp" = load {i1, %"File"}, {i1, %"File"}* %"if_result"
  ret {i1, %"File"} %"iftmp"
}

define {i1, %"File"} @"File_open_append"(%"Path" %"path")
{
entry:
  %"if_result" = alloca {i1, %"File"}
  %"path.1" = alloca %"Path"
  store %"Path" %"path", %"Path"* %"path.1"
  %"path.2" = load %"Path", %"Path"* %"path.1"
  %"methodcall" = call i8* @"Path_as_str"(%"Path" %"path.2")
  %"path_ptr" = alloca i8*
  store i8* %"methodcall", i8** %"path_ptr"
  %"path_ptr.1" = load i8*, i8** %"path_ptr"
  %"trunc" = trunc i64 1089 to i32
  %"calltmp" = call i32 (i8*, i32, ...) @"open"(i8* %"path_ptr.1", i32 %"trunc", i64 420)
  %"fd" = alloca i32
  store i32 %"calltmp", i32* %"fd"
  %"fd.1" = load i32, i32* %"fd"
  %"trunc.1" = trunc i64 0 to i32
  %"lttmp" = icmp slt i32 %"fd.1", %"trunc.1"
  br i1 %"lttmp", label %"then", label %"else"
then:
  %".7" = insertvalue {i1, %"File"} undef, i1 0, 0
  store {i1, %"File"} %".7", {i1, %"File"}* %"if_result"
  br label %"ifcont"
else:
  %"fd.2" = load i32, i32* %"fd"
  %".8" = insertvalue %"File" undef, i32 %"fd.2", 0
  %".11" = insertvalue {i1, %"File"} undef, i1 1, 0
  %"some_else" = insertvalue {i1, %"File"} %".11", %"File" %".8", 1
  store {i1, %"File"} %"some_else", {i1, %"File"}* %"if_result"
  br label %"ifcont"
ifcont:
  %"iftmp" = load {i1, %"File"}, {i1, %"File"}* %"if_result"
  ret {i1, %"File"} %"iftmp"
}

define {i1, %"Data"} @"File_read"(%"File"* %"self", i64 %"size")
{
entry:
  %"if_let_result" = alloca {i1, %"Data"}
  %"size.1" = alloca i64
  store i64 %"size", i64* %"size.1"
  %"size.2" = load i64, i64* %"size.1"
  %"bytes_to_read" = alloca i64
  store i64 %"size.2", i64* %"bytes_to_read"
  %"bytes_to_read.1" = load i64, i64* %"bytes_to_read"
  %"letmp" = icmp sle i64 %"bytes_to_read.1", 0
  br i1 %"letmp", label %"then", label %"else"
then:
  %"self.1" = load %"File", %"File"* %"self"
  %".7" = extractvalue %"File" %"self.1", 0
  %"trunc" = trunc i64 1 to i32
  %"calltmp" = call i64 @"lseek"(i32 %".7", i64 0, i32 %"trunc")
  %"current_pos" = alloca i64
  store i64 %"calltmp", i64* %"current_pos"
  %"current_pos.1" = load i64, i64* %"current_pos"
  %"lttmp" = icmp slt i64 %"current_pos.1", 0
  br i1 %"lttmp", label %"then.1", label %"else.1"
else:
  br label %"ifcont"
ifcont:
  %"bytes_to_read.2" = load i64, i64* %"bytes_to_read"
  %"eqtmp" = icmp eq i64 %"bytes_to_read.2", 0
  br i1 %"eqtmp", label %"then.3", label %"else.3"
then.1:
  %".10" = insertvalue {i1, %"Data"} undef, i1 0, 0
  ret {i1, %"Data"} %".10"
else.1:
  br label %"ifcont.1"
ifcont.1:
  %"self.2" = load %"File", %"File"* %"self"
  %".13" = extractvalue %"File" %"self.2", 0
  %"trunc.1" = trunc i64 2 to i32
  %"calltmp.1" = call i64 @"lseek"(i32 %".13", i64 0, i32 %"trunc.1")
  %"end_pos" = alloca i64
  store i64 %"calltmp.1", i64* %"end_pos"
  %"end_pos.1" = load i64, i64* %"end_pos"
  %"lttmp.1" = icmp slt i64 %"end_pos.1", 0
  br i1 %"lttmp.1", label %"then.2", label %"else.2"
then.2:
  %".16" = insertvalue {i1, %"Data"} undef, i1 0, 0
  ret {i1, %"Data"} %".16"
else.2:
  br label %"ifcont.2"
ifcont.2:
  %"end_pos.2" = load i64, i64* %"end_pos"
  %"current_pos.2" = load i64, i64* %"current_pos"
  %"subtmp" = sub i64 %"end_pos.2", %"current_pos.2"
  store i64 %"subtmp", i64* %"bytes_to_read"
  %"self.3" = load %"File", %"File"* %"self"
  %".20" = extractvalue %"File" %"self.3", 0
  %"current_pos.3" = load i64, i64* %"current_pos"
  %"trunc.2" = trunc i64 0 to i32
  %"calltmp.2" = call i64 @"lseek"(i32 %".20", i64 %"current_pos.3", i32 %"trunc.2")
  br label %"ifcont"
then.3:
  %".24" = insertvalue {i1, %"Data"} undef, i1 1, 0
  %".25" = insertvalue {i1, %"Data"} %".24", %"Data" undef, 1
  ret {i1, %"Data"} %".25"
else.3:
  br label %"ifcont.3"
ifcont.3:
  %"bytes_to_read.3" = load i64, i64* %"bytes_to_read"
  %"calltmp.3" = call i8* @"malloc"(i64 %"bytes_to_read.3")
  %"is_not_null" = icmp ne i8* %"calltmp.3", null
  %"opt_flag" = insertvalue {i1, i8*} undef, i1 %"is_not_null", 0
  %"opt_val" = insertvalue {i1, i8*} %"opt_flag", i8* %"calltmp.3", 1
  %"is_some" = extractvalue {i1, i8*} %"opt_val", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %"opt_val", 1
  %"buf" = alloca i8*
  store i8* %"unwrapped", i8** %"buf"
  %"self.4" = load %"File", %"File"* %"self"
  %".30" = extractvalue %"File" %"self.4", 0
  %"buf.1" = load i8*, i8** %"buf"
  %"bytes_to_read.4" = load i64, i64* %"bytes_to_read"
  %"calltmp.4" = call i64 @"read"(i32 %".30", i8* %"buf.1", i64 %"bytes_to_read.4")
  %"bytes_read" = alloca i64
  store i64 %"calltmp.4", i64* %"bytes_read"
  %"bytes_read.1" = load i64, i64* %"bytes_read"
  %"lttmp.2" = icmp slt i64 %"bytes_read.1", 0
  br i1 %"lttmp.2", label %"then.4", label %"else.4"
if_let_else:
  %".43" = insertvalue {i1, %"Data"} undef, i1 0, 0
  store {i1, %"Data"} %".43", {i1, %"Data"}* %"if_let_result"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp" = load {i1, %"Data"}, {i1, %"Data"}* %"if_let_result"
  ret {i1, %"Data"} %"if_let_tmp"
then.4:
  %"buf.2" = load i8*, i8** %"buf"
  call void @"free"(i8* %"buf.2")
  %".33" = insertvalue {i1, %"Data"} undef, i1 0, 0
  ret {i1, %"Data"} %".33"
else.4:
  br label %"ifcont.4"
ifcont.4:
  %"bytes_read.2" = load i64, i64* %"bytes_read"
  %".36" = call %"Data" @"Data_init_capacity"(i64 %"bytes_read.2")
  %"data" = alloca %"Data"
  store %"Data" %".36", %"Data"* %"data"
  %"i" = alloca i64
  store i64 0, i64* %"i"
  br label %"while.cond"
while.cond:
  %"i.1" = load i64, i64* %"i"
  %"bytes_read.3" = load i64, i64* %"bytes_read"
  %"lttmp.3" = icmp slt i64 %"i.1", %"bytes_read.3"
  br i1 %"lttmp.3", label %"while.body", label %"while.end"
while.body:
  %"data.1" = load %"Data", %"Data"* %"data"
  %"buf.3" = load i8*, i8** %"buf"
  %"i.2" = load i64, i64* %"i"
  %"ptr_idx" = getelementptr i8, i8* %"buf.3", i64 %"i.2"
  %"ptr_elem" = load i8, i8* %"ptr_idx"
  call void @"Data_push"(%"Data"* %"data", i8 %"ptr_elem")
  %"i.3" = load i64, i64* %"i"
  %"addtmp" = add i64 %"i.3", 1
  store i64 %"addtmp", i64* %"i"
  br label %"while.cond"
while.end:
  %"buf.4" = load i8*, i8** %"buf"
  call void @"free"(i8* %"buf.4")
  %"data_moved" = load %"Data", %"Data"* %"data"
  %".44" = insertvalue {i1, %"Data"} undef, i1 1, 0
  %"some_then" = insertvalue {i1, %"Data"} %".44", %"Data" %"data_moved", 1
  store {i1, %"Data"} %"some_then", {i1, %"Data"}* %"if_let_result"
  br label %"if_let_merge"
}

define {i1, i64} @"File_write"(%"File" %"self", %"Data" %"data")
{
entry:
  %"if_let_result" = alloca {i1, i64}
  %"if_result" = alloca {i1, i64}
  %"self.1" = alloca %"File"
  store %"File" %"self", %"File"* %"self.1"
  %"data.1" = alloca %"Data"
  store %"Data" %"data", %"Data"* %"data.1"
  %"data.2" = load %"Data", %"Data"* %"data.1"
  %"methodcall" = call i64 @"Data_len"(%"Data" %"data.2")
  %"eqtmp" = icmp eq i64 %"methodcall", 0
  br i1 %"eqtmp", label %"then", label %"else"
then:
  %".7" = insertvalue {i1, i64} undef, i1 1, 0
  %".8" = insertvalue {i1, i64} %".7", i64 0, 1
  ret {i1, i64} %".8"
else:
  br label %"ifcont"
ifcont:
  %"data.3" = load %"Data", %"Data"* %"data.1"
  %"methodcall.1" = call i64 @"Data_len"(%"Data" %"data.3")
  %"calltmp" = call i8* @"malloc"(i64 %"methodcall.1")
  %"is_not_null" = icmp ne i8* %"calltmp", null
  %"opt_flag" = insertvalue {i1, i8*} undef, i1 %"is_not_null", 0
  %"opt_val" = insertvalue {i1, i8*} %"opt_flag", i8* %"calltmp", 1
  %"is_some" = extractvalue {i1, i8*} %"opt_val", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %"opt_val", 1
  %"buf" = alloca i8*
  store i8* %"unwrapped", i8** %"buf"
  %"i" = alloca i64
  store i64 0, i64* %"i"
  br label %"while.cond"
if_let_else:
  %".32" = insertvalue {i1, i64} undef, i1 0, 0
  store {i1, i64} %".32", {i1, i64}* %"if_let_result"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp" = load {i1, i64}, {i1, i64}* %"if_let_result"
  ret {i1, i64} %"if_let_tmp"
while.cond:
  %"i.1" = load i64, i64* %"i"
  %"data.4" = load %"Data", %"Data"* %"data.1"
  %"methodcall.2" = call i64 @"Data_len"(%"Data" %"data.4")
  %"lttmp" = icmp slt i64 %"i.1", %"methodcall.2"
  br i1 %"lttmp", label %"while.body", label %"while.end"
while.body:
  %"data.5" = load %"Data", %"Data"* %"data.1"
  %"i.2" = load i64, i64* %"i"
  %"methodcall.3" = call {i1, i8} @"Data_get"(%"Data" %"data.5", i64 %"i.2")
  %"is_some.1" = extractvalue {i1, i8} %"methodcall.3", 0
  br i1 %"is_some.1", label %"if_let_then.1", label %"if_let_else.1"
while.end:
  %"self.2" = load %"File", %"File"* %"self.1"
  %".23" = extractvalue %"File" %"self.2", 0
  %"buf.1" = load i8*, i8** %"buf"
  %"data.6" = load %"Data", %"Data"* %"data.1"
  %"methodcall.4" = call i64 @"Data_len"(%"Data" %"data.6")
  %"calltmp.1" = call i64 @"write"(i32 %".23", i8* %"buf.1", i64 %"methodcall.4")
  %"written" = alloca i64
  store i64 %"calltmp.1", i64* %"written"
  %"buf.2" = load i8*, i8** %"buf"
  call void @"free"(i8* %"buf.2")
  %"written.1" = load i64, i64* %"written"
  %"lttmp.1" = icmp slt i64 %"written.1", 0
  br i1 %"lttmp.1", label %"then.1", label %"else.1"
if_let_then.1:
  %"unwrapped.1" = extractvalue {i1, i8} %"methodcall.3", 1
  %"b" = alloca i8
  store i8 %"unwrapped.1", i8* %"b"
  %"b.1" = load i8, i8* %"b"
  %"i.3" = load i64, i64* %"i"
  %"container" = load i8*, i8** %"buf"
  %"ptr_elem" = getelementptr i8, i8* %"container", i64 %"i.3"
  store i8 %"b.1", i8* %"ptr_elem"
  br label %"if_let_merge.1"
if_let_else.1:
  br label %"if_let_merge.1"
if_let_merge.1:
  %"i.4" = load i64, i64* %"i"
  %"addtmp" = add i64 %"i.4", 1
  store i64 %"addtmp", i64* %"i"
  br label %"while.cond"
then.1:
  %".26" = insertvalue {i1, i64} undef, i1 0, 0
  store {i1, i64} %".26", {i1, i64}* %"if_result"
  br label %"ifcont.1"
else.1:
  %"written.2" = load i64, i64* %"written"
  %".29" = insertvalue {i1, i64} undef, i1 1, 0
  %"some_else" = insertvalue {i1, i64} %".29", i64 %"written.2", 1
  store {i1, i64} %"some_else", {i1, i64}* %"if_result"
  br label %"ifcont.1"
ifcont.1:
  %"iftmp" = load {i1, i64}, {i1, i64}* %"if_result"
  store {i1, i64} %"iftmp", {i1, i64}* %"if_let_result"
  br label %"if_let_merge"
}

define {i1, i64} @"File_seek_start"(%"File" %"self", i64 %"offset")
{
entry:
  %"if_result" = alloca {i1, i64}
  %"self.1" = alloca %"File"
  store %"File" %"self", %"File"* %"self.1"
  %"offset.1" = alloca i64
  store i64 %"offset", i64* %"offset.1"
  %"self.2" = load %"File", %"File"* %"self.1"
  %".6" = extractvalue %"File" %"self.2", 0
  %"offset.2" = load i64, i64* %"offset.1"
  %"trunc" = trunc i64 0 to i32
  %"calltmp" = call i64 @"lseek"(i32 %".6", i64 %"offset.2", i32 %"trunc")
  %"result" = alloca i64
  store i64 %"calltmp", i64* %"result"
  %"result.1" = load i64, i64* %"result"
  %"lttmp" = icmp slt i64 %"result.1", 0
  br i1 %"lttmp", label %"then", label %"else"
then:
  %".9" = insertvalue {i1, i64} undef, i1 0, 0
  store {i1, i64} %".9", {i1, i64}* %"if_result"
  br label %"ifcont"
else:
  %"result.2" = load i64, i64* %"result"
  %".12" = insertvalue {i1, i64} undef, i1 1, 0
  %"some_else" = insertvalue {i1, i64} %".12", i64 %"result.2", 1
  store {i1, i64} %"some_else", {i1, i64}* %"if_result"
  br label %"ifcont"
ifcont:
  %"iftmp" = load {i1, i64}, {i1, i64}* %"if_result"
  ret {i1, i64} %"iftmp"
}

define {i1, i64} @"File_seek_current"(%"File" %"self", i64 %"offset")
{
entry:
  %"if_result" = alloca {i1, i64}
  %"self.1" = alloca %"File"
  store %"File" %"self", %"File"* %"self.1"
  %"offset.1" = alloca i64
  store i64 %"offset", i64* %"offset.1"
  %"self.2" = load %"File", %"File"* %"self.1"
  %".6" = extractvalue %"File" %"self.2", 0
  %"offset.2" = load i64, i64* %"offset.1"
  %"trunc" = trunc i64 1 to i32
  %"calltmp" = call i64 @"lseek"(i32 %".6", i64 %"offset.2", i32 %"trunc")
  %"result" = alloca i64
  store i64 %"calltmp", i64* %"result"
  %"result.1" = load i64, i64* %"result"
  %"lttmp" = icmp slt i64 %"result.1", 0
  br i1 %"lttmp", label %"then", label %"else"
then:
  %".9" = insertvalue {i1, i64} undef, i1 0, 0
  store {i1, i64} %".9", {i1, i64}* %"if_result"
  br label %"ifcont"
else:
  %"result.2" = load i64, i64* %"result"
  %".12" = insertvalue {i1, i64} undef, i1 1, 0
  %"some_else" = insertvalue {i1, i64} %".12", i64 %"result.2", 1
  store {i1, i64} %"some_else", {i1, i64}* %"if_result"
  br label %"ifcont"
ifcont:
  %"iftmp" = load {i1, i64}, {i1, i64}* %"if_result"
  ret {i1, i64} %"iftmp"
}

define {i1, i64} @"File_seek_end"(%"File" %"self", i64 %"offset")
{
entry:
  %"if_result" = alloca {i1, i64}
  %"self.1" = alloca %"File"
  store %"File" %"self", %"File"* %"self.1"
  %"offset.1" = alloca i64
  store i64 %"offset", i64* %"offset.1"
  %"self.2" = load %"File", %"File"* %"self.1"
  %".6" = extractvalue %"File" %"self.2", 0
  %"offset.2" = load i64, i64* %"offset.1"
  %"trunc" = trunc i64 2 to i32
  %"calltmp" = call i64 @"lseek"(i32 %".6", i64 %"offset.2", i32 %"trunc")
  %"result" = alloca i64
  store i64 %"calltmp", i64* %"result"
  %"result.1" = load i64, i64* %"result"
  %"lttmp" = icmp slt i64 %"result.1", 0
  br i1 %"lttmp", label %"then", label %"else"
then:
  %".9" = insertvalue {i1, i64} undef, i1 0, 0
  store {i1, i64} %".9", {i1, i64}* %"if_result"
  br label %"ifcont"
else:
  %"result.2" = load i64, i64* %"result"
  %".12" = insertvalue {i1, i64} undef, i1 1, 0
  %"some_else" = insertvalue {i1, i64} %".12", i64 %"result.2", 1
  store {i1, i64} %"some_else", {i1, i64}* %"if_result"
  br label %"ifcont"
ifcont:
  %"iftmp" = load {i1, i64}, {i1, i64}* %"if_result"
  ret {i1, i64} %"iftmp"
}

define {i1, i64} @"File_position"(%"File" %"self")
{
entry:
  %"if_result" = alloca {i1, i64}
  %"self.1" = alloca %"File"
  store %"File" %"self", %"File"* %"self.1"
  %"self.2" = load %"File", %"File"* %"self.1"
  %".4" = extractvalue %"File" %"self.2", 0
  %"trunc" = trunc i64 1 to i32
  %"calltmp" = call i64 @"lseek"(i32 %".4", i64 0, i32 %"trunc")
  %"result" = alloca i64
  store i64 %"calltmp", i64* %"result"
  %"result.1" = load i64, i64* %"result"
  %"lttmp" = icmp slt i64 %"result.1", 0
  br i1 %"lttmp", label %"then", label %"else"
then:
  %".7" = insertvalue {i1, i64} undef, i1 0, 0
  store {i1, i64} %".7", {i1, i64}* %"if_result"
  br label %"ifcont"
else:
  %"result.2" = load i64, i64* %"result"
  %".10" = insertvalue {i1, i64} undef, i1 1, 0
  %"some_else" = insertvalue {i1, i64} %".10", i64 %"result.2", 1
  store {i1, i64} %"some_else", {i1, i64}* %"if_result"
  br label %"ifcont"
ifcont:
  %"iftmp" = load {i1, i64}, {i1, i64}* %"if_result"
  ret {i1, i64} %"iftmp"
}

define i1 @"File_exists"(%"Path" %"path")
{
entry:
  %"path.1" = alloca %"Path"
  store %"Path" %"path", %"Path"* %"path.1"
  %"path.2" = load %"Path", %"Path"* %"path.1"
  %"methodcall" = call i8* @"Path_as_str"(%"Path" %"path.2")
  %"ptr" = alloca i8*
  store i8* %"methodcall", i8** %"ptr"
  %"ptr.1" = load i8*, i8** %"ptr"
  %"trunc" = trunc i64 0 to i32
  %"calltmp" = call i32 @"access"(i8* %"ptr.1", i32 %"trunc")
  %"trunc.1" = trunc i64 0 to i32
  %"eqtmp" = icmp eq i32 %"calltmp", %"trunc.1"
  ret i1 %"eqtmp"
}

define i1 @"File_remove"(%"Path" %"path")
{
entry:
  %"path.1" = alloca %"Path"
  store %"Path" %"path", %"Path"* %"path.1"
  %"path.2" = load %"Path", %"Path"* %"path.1"
  %"methodcall" = call i8* @"Path_as_str"(%"Path" %"path.2")
  %"ptr" = alloca i8*
  store i8* %"methodcall", i8** %"ptr"
  %"ptr.1" = load i8*, i8** %"ptr"
  %"calltmp" = call i32 @"unlink"(i8* %"ptr.1")
  %"trunc" = trunc i64 0 to i32
  %"eqtmp" = icmp eq i32 %"calltmp", %"trunc"
  ret i1 %"eqtmp"
}

define i1 @"File_rename"(%"Path" %"from_path", %"Path" %"to_path")
{
entry:
  %"from_path.1" = alloca %"Path"
  store %"Path" %"from_path", %"Path"* %"from_path.1"
  %"to_path.1" = alloca %"Path"
  store %"Path" %"to_path", %"Path"* %"to_path.1"
  %"from_path.2" = load %"Path", %"Path"* %"from_path.1"
  %"methodcall" = call i8* @"Path_as_str"(%"Path" %"from_path.2")
  %"from_ptr" = alloca i8*
  store i8* %"methodcall", i8** %"from_ptr"
  %"to_path.2" = load %"Path", %"Path"* %"to_path.1"
  %"methodcall.1" = call i8* @"Path_as_str"(%"Path" %"to_path.2")
  %"to_ptr" = alloca i8*
  store i8* %"methodcall.1", i8** %"to_ptr"
  %"from_ptr.1" = load i8*, i8** %"from_ptr"
  %"to_ptr.1" = load i8*, i8** %"to_ptr"
  %"calltmp" = call i32 @"rename"(i8* %"from_ptr.1", i8* %"to_ptr.1")
  %"trunc" = trunc i64 0 to i32
  %"eqtmp" = icmp eq i32 %"calltmp", %"trunc"
  ret i1 %"eqtmp"
}

define void @"File_deinit"(%"File"* %"self")
{
entry:
  %"self.1" = load %"File", %"File"* %"self"
  %".3" = extractvalue %"File" %"self.1", 0
  %"trunc" = trunc i64 0 to i32
  %"getmp" = icmp sge i32 %".3", %"trunc"
  br i1 %"getmp", label %"then", label %"else"
then:
  %"self.2" = load %"File", %"File"* %"self"
  %".5" = extractvalue %"File" %"self.2", 0
  %"calltmp" = call i32 @"close"(i32 %".5")
  br label %"ifcont"
else:
  br label %"ifcont"
ifcont:
  ret void
}

define %"Path" @"Path_init_s"(i8* %"s")
{
entry:
  %"s.1" = alloca i8*
  store i8* %"s", i8** %"s.1"
  %"s.2" = load i8*, i8** %"s.1"
  %".4" = insertvalue %"Path" undef, i8* %"s.2", 0
  ret %"Path" %".4"
}

define i8* @"Path_as_str"(%"Path" %"self")
{
entry:
  %"self.1" = alloca %"Path"
  store %"Path" %"self", %"Path"* %"self.1"
  %"self.2" = load %"Path", %"Path"* %"self.1"
  %".4" = extractvalue %"Path" %"self.2", 0
  ret i8* %".4"
}

define {i1, %"Path"} @"Path_parent"(%"Path" %"self")
{
entry:
  %"if_let_result" = alloca {i1, %"Path"}
  %"self.1" = alloca %"Path"
  store %"Path" %"self", %"Path"* %"self.1"
  %"self.2" = load %"Path", %"Path"* %"self.1"
  %".4" = extractvalue %"Path" %"self.2", 0
  %"methodcall" = call i64 @"String_len"(i8* %".4")
  %"len" = alloca i64
  store i64 %"methodcall", i64* %"len"
  %"len.1" = load i64, i64* %"len"
  %"eqtmp" = icmp eq i64 %"len.1", 0
  br i1 %"eqtmp", label %"then", label %"else"
then:
  %".7" = insertvalue {i1, %"Path"} undef, i1 0, 0
  ret {i1, %"Path"} %".7"
else:
  br label %"ifcont"
ifcont:
  %"self.3" = load %"Path", %"Path"* %"self.1"
  %".10" = extractvalue %"Path" %"self.3", 0
  %"trunc" = trunc i64 47 to i8
  %"methodcall.1" = call {i1, i64} @"String_last_index_of_char"(i8* %".10", i8 %"trunc")
  %"is_some" = extractvalue {i1, i64} %"methodcall.1", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, i64} %"methodcall.1", 1
  %"last_sep" = alloca i64
  store i64 %"unwrapped", i64* %"last_sep"
  %"last_sep.1" = load i64, i64* %"last_sep"
  %"eqtmp.1" = icmp eq i64 %"last_sep.1", 0
  br i1 %"eqtmp.1", label %"then.1", label %"else.1"
if_let_else:
  %".26" = insertvalue {i1, %"Path"} undef, i1 0, 0
  store {i1, %"Path"} %".26", {i1, %"Path"}* %"if_let_result"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp" = load {i1, %"Path"}, {i1, %"Path"}* %"if_let_result"
  ret {i1, %"Path"} %"if_let_tmp"
then.1:
  %"len.2" = load i64, i64* %"len"
  %"eqtmp.2" = icmp eq i64 %"len.2", 1
  br i1 %"eqtmp.2", label %"then.2", label %"else.2"
else.1:
  br label %"ifcont.1"
ifcont.1:
  %"self.4" = load %"Path", %"Path"* %"self.1"
  %".24" = extractvalue %"Path" %"self.4", 0
  %"last_sep.2" = load i64, i64* %"last_sep"
  %"methodcall.2" = call i8* @"String_substring"(i8* %".24", i64 0, i64 %"last_sep.2")
  %".25" = insertvalue %"Path" undef, i8* %"methodcall.2", 0
  %".27" = insertvalue {i1, %"Path"} undef, i1 1, 0
  %"some_then" = insertvalue {i1, %"Path"} %".27", %"Path" %".25", 1
  store {i1, %"Path"} %"some_then", {i1, %"Path"}* %"if_let_result"
  br label %"if_let_merge"
then.2:
  %".15" = insertvalue {i1, %"Path"} undef, i1 0, 0
  ret {i1, %"Path"} %".15"
else.2:
  br label %"ifcont.2"
ifcont.2:
  %".18" = getelementptr inbounds [2 x i8], [2 x i8]* @".str.2", i32 0, i32 0
  %".19" = insertvalue %"Path" undef, i8* %".18", 0
  %".20" = insertvalue {i1, %"Path"} undef, i1 1, 0
  %".21" = insertvalue {i1, %"Path"} %".20", %"Path" %".19", 1
  ret {i1, %"Path"} %".21"
}

define {i1, i8*} @"Path_file_name"(%"Path" %"self")
{
entry:
  %"if_let_result" = alloca i8*
  %"self.1" = alloca %"Path"
  store %"Path" %"self", %"Path"* %"self.1"
  %"self.2" = load %"Path", %"Path"* %"self.1"
  %".4" = extractvalue %"Path" %"self.2", 0
  %"methodcall" = call i64 @"String_len"(i8* %".4")
  %"len" = alloca i64
  store i64 %"methodcall", i64* %"len"
  %"len.1" = load i64, i64* %"len"
  %"eqtmp" = icmp eq i64 %"len.1", 0
  br i1 %"eqtmp", label %"then", label %"else"
then:
  %".7" = insertvalue {i1, i8*} undef, i1 0, 0
  ret {i1, i8*} %".7"
else:
  br label %"ifcont"
ifcont:
  %"self.3" = load %"Path", %"Path"* %"self.1"
  %".10" = extractvalue %"Path" %"self.3", 0
  %"trunc" = trunc i64 47 to i8
  %"methodcall.1" = call {i1, i64} @"String_last_index_of_char"(i8* %".10", i8 %"trunc")
  %"is_some" = extractvalue {i1, i64} %"methodcall.1", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, i64} %"methodcall.1", 1
  %"last_sep" = alloca i64
  store i64 %"unwrapped", i64* %"last_sep"
  %"last_sep.1" = load i64, i64* %"last_sep"
  %"len.2" = load i64, i64* %"len"
  %"subtmp" = sub i64 %"len.2", 1
  %"eqtmp.1" = icmp eq i64 %"last_sep.1", %"subtmp"
  br i1 %"eqtmp.1", label %"then.1", label %"else.1"
if_let_else:
  %"self.5" = load %"Path", %"Path"* %"self.1"
  %".18" = extractvalue %"Path" %"self.5", 0
  store i8* %".18", i8** %"if_let_result"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp" = load i8*, i8** %"if_let_result"
  %".23" = insertvalue {i1, i8*} undef, i1 1, 0
  %".24" = insertvalue {i1, i8*} %".23", i8* %"if_let_tmp", 1
  ret {i1, i8*} %".24"
then.1:
  %".14" = insertvalue {i1, i8*} undef, i1 0, 0
  ret {i1, i8*} %".14"
else.1:
  br label %"ifcont.1"
ifcont.1:
  %"self.4" = load %"Path", %"Path"* %"self.1"
  %".17" = extractvalue %"Path" %"self.4", 0
  %"last_sep.2" = load i64, i64* %"last_sep"
  %"addtmp" = add i64 %"last_sep.2", 1
  %"len.3" = load i64, i64* %"len"
  %"methodcall.2" = call i8* @"String_substring"(i8* %".17", i64 %"addtmp", i64 %"len.3")
  store i8* %"methodcall.2", i8** %"if_let_result"
  br label %"if_let_merge"
}

define {i1, i8*} @"Path_ext"(%"Path" %"self")
{
entry:
  %"if_let_result.1" = alloca {i1, i8*}
  %"if_let_result" = alloca {i1, i8*}
  %"self.1" = alloca %"Path"
  store %"Path" %"self", %"Path"* %"self.1"
  %"self.2" = load %"Path", %"Path"* %"self.1"
  %"methodcall" = call {i1, i8*} @"Path_file_name"(%"Path" %"self.2")
  %"is_some" = extractvalue {i1, i8*} %"methodcall", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %"methodcall", 1
  %"name" = alloca i8*
  store i8* %"unwrapped", i8** %"name"
  %"name.1" = load i8*, i8** %"name"
  %"trunc" = trunc i64 46 to i8
  %"methodcall.1" = call {i1, i64} @"String_last_index_of_char"(i8* %"name.1", i8 %"trunc")
  %"is_some.1" = extractvalue {i1, i64} %"methodcall.1", 0
  br i1 %"is_some.1", label %"if_let_then.1", label %"if_let_else.1"
if_let_else:
  %".23" = insertvalue {i1, i8*} undef, i1 0, 0
  store {i1, i8*} %".23", {i1, i8*}* %"if_let_result.1"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp.1" = load {i1, i8*}, {i1, i8*}* %"if_let_result.1"
  ret {i1, i8*} %"if_let_tmp.1"
if_let_then.1:
  %"unwrapped.1" = extractvalue {i1, i64} %"methodcall.1", 1
  %"last_dot" = alloca i64
  store i64 %"unwrapped.1", i64* %"last_dot"
  %"last_dot.1" = load i64, i64* %"last_dot"
  %"eqtmp" = icmp eq i64 %"last_dot.1", 0
  br i1 %"eqtmp", label %"then", label %"else"
if_let_else.1:
  %".17" = insertvalue {i1, i8*} undef, i1 0, 0
  store {i1, i8*} %".17", {i1, i8*}* %"if_let_result"
  br label %"if_let_merge.1"
if_let_merge.1:
  %"if_let_tmp" = load {i1, i8*}, {i1, i8*}* %"if_let_result"
  store {i1, i8*} %"if_let_tmp", {i1, i8*}* %"if_let_result.1"
  br label %"if_let_merge"
then:
  %".9" = insertvalue {i1, i8*} undef, i1 0, 0
  ret {i1, i8*} %".9"
else:
  br label %"ifcont"
ifcont:
  %"name.2" = load i8*, i8** %"name"
  %"methodcall.2" = call i64 @"String_len"(i8* %"name.2")
  %"len" = alloca i64
  store i64 %"methodcall.2", i64* %"len"
  %"last_dot.2" = load i64, i64* %"last_dot"
  %"len.1" = load i64, i64* %"len"
  %"subtmp" = sub i64 %"len.1", 1
  %"eqtmp.1" = icmp eq i64 %"last_dot.2", %"subtmp"
  br i1 %"eqtmp.1", label %"then.1", label %"else.1"
then.1:
  %".14" = insertvalue {i1, i8*} undef, i1 0, 0
  ret {i1, i8*} %".14"
else.1:
  br label %"ifcont.1"
ifcont.1:
  %"name.3" = load i8*, i8** %"name"
  %"last_dot.3" = load i64, i64* %"last_dot"
  %"addtmp" = add i64 %"last_dot.3", 1
  %"len.2" = load i64, i64* %"len"
  %"methodcall.3" = call i8* @"String_substring"(i8* %"name.3", i64 %"addtmp", i64 %"len.2")
  %".18" = insertvalue {i1, i8*} undef, i1 1, 0
  %"some_then" = insertvalue {i1, i8*} %".18", i8* %"methodcall.3", 1
  store {i1, i8*} %"some_then", {i1, i8*}* %"if_let_result"
  br label %"if_let_merge.1"
}

define {i1, i8*} @"Path_stem"(%"Path" %"self")
{
entry:
  %"if_let_result.1" = alloca {i1, i8*}
  %"if_let_result" = alloca i8*
  %"self.1" = alloca %"Path"
  store %"Path" %"self", %"Path"* %"self.1"
  %"self.2" = load %"Path", %"Path"* %"self.1"
  %"methodcall" = call {i1, i8*} @"Path_file_name"(%"Path" %"self.2")
  %"is_some" = extractvalue {i1, i8*} %"methodcall", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %"methodcall", 1
  %"name" = alloca i8*
  store i8* %"unwrapped", i8** %"name"
  %"name.1" = load i8*, i8** %"name"
  %"trunc" = trunc i64 46 to i8
  %"methodcall.1" = call {i1, i64} @"String_last_index_of_char"(i8* %"name.1", i8 %"trunc")
  %"is_some.1" = extractvalue {i1, i64} %"methodcall.1", 0
  br i1 %"is_some.1", label %"if_let_then.1", label %"if_let_else.1"
if_let_else:
  %".17" = insertvalue {i1, i8*} undef, i1 0, 0
  store {i1, i8*} %".17", {i1, i8*}* %"if_let_result.1"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp.1" = load {i1, i8*}, {i1, i8*}* %"if_let_result.1"
  ret {i1, i8*} %"if_let_tmp.1"
if_let_then.1:
  %"unwrapped.1" = extractvalue {i1, i64} %"methodcall.1", 1
  %"last_dot" = alloca i64
  store i64 %"unwrapped.1", i64* %"last_dot"
  %"last_dot.1" = load i64, i64* %"last_dot"
  %"eqtmp" = icmp eq i64 %"last_dot.1", 0
  br i1 %"eqtmp", label %"then", label %"else"
if_let_else.1:
  %"name.4" = load i8*, i8** %"name"
  store i8* %"name.4", i8** %"if_let_result"
  br label %"if_let_merge.1"
if_let_merge.1:
  %"if_let_tmp" = load i8*, i8** %"if_let_result"
  %".18" = insertvalue {i1, i8*} undef, i1 1, 0
  %"some_then" = insertvalue {i1, i8*} %".18", i8* %"if_let_tmp", 1
  store {i1, i8*} %"some_then", {i1, i8*}* %"if_let_result.1"
  br label %"if_let_merge"
then:
  %"name.2" = load i8*, i8** %"name"
  %".9" = insertvalue {i1, i8*} undef, i1 1, 0
  %".10" = insertvalue {i1, i8*} %".9", i8* %"name.2", 1
  ret {i1, i8*} %".10"
else:
  br label %"ifcont"
ifcont:
  %"name.3" = load i8*, i8** %"name"
  %"last_dot.2" = load i64, i64* %"last_dot"
  %"methodcall.2" = call i8* @"String_substring"(i8* %"name.3", i64 0, i64 %"last_dot.2")
  store i8* %"methodcall.2", i8** %"if_let_result"
  br label %"if_let_merge.1"
}

define %"Path" @"Path_join"(%"Path" %"self", i8* %"other")
{
entry:
  %"if_let_result" = alloca %"Path"
  %"self.1" = alloca %"Path"
  store %"Path" %"self", %"Path"* %"self.1"
  %"other.1" = alloca i8*
  store i8* %"other", i8** %"other.1"
  %"self.2" = load %"Path", %"Path"* %"self.1"
  %".6" = extractvalue %"Path" %"self.2", 0
  %"methodcall" = call i64 @"String_len"(i8* %".6")
  %"self_len" = alloca i64
  store i64 %"methodcall", i64* %"self_len"
  %"other.2" = load i8*, i8** %"other.1"
  %"methodcall.1" = call i64 @"String_len"(i8* %"other.2")
  %"other_len" = alloca i64
  store i64 %"methodcall.1", i64* %"other_len"
  %"self_len.1" = load i64, i64* %"self_len"
  %"eqtmp" = icmp eq i64 %"self_len.1", 0
  br i1 %"eqtmp", label %"then", label %"else"
then:
  %"other.3" = load i8*, i8** %"other.1"
  %".10" = insertvalue %"Path" undef, i8* %"other.3", 0
  ret %"Path" %".10"
else:
  br label %"ifcont"
ifcont:
  %"other_len.1" = load i64, i64* %"other_len"
  %"eqtmp.1" = icmp eq i64 %"other_len.1", 0
  br i1 %"eqtmp.1", label %"then.1", label %"else.1"
then.1:
  %"self.3" = load %"Path", %"Path"* %"self.1"
  %".14" = extractvalue %"Path" %"self.3", 0
  %".15" = insertvalue %"Path" undef, i8* %".14", 0
  ret %"Path" %".15"
else.1:
  br label %"ifcont.1"
ifcont.1:
  %"other.4" = load i8*, i8** %"other.1"
  %"methodcall.2" = call i8 @"String_byte_at"(i8* %"other.4", i64 0)
  %"trunc" = trunc i64 47 to i8
  %"eqtmp.2" = icmp eq i8 %"methodcall.2", %"trunc"
  br i1 %"eqtmp.2", label %"then.2", label %"else.2"
then.2:
  %"other.5" = load i8*, i8** %"other.1"
  %".19" = insertvalue %"Path" undef, i8* %"other.5", 0
  ret %"Path" %".19"
else.2:
  br label %"ifcont.2"
ifcont.2:
  %"self.4" = load %"Path", %"Path"* %"self.1"
  %".22" = extractvalue %"Path" %"self.4", 0
  %"self_len.2" = load i64, i64* %"self_len"
  %"subtmp" = sub i64 %"self_len.2", 1
  %"methodcall.3" = call i8 @"String_byte_at"(i8* %".22", i64 %"subtmp")
  %"trunc.1" = trunc i64 47 to i8
  %"netmp" = icmp ne i8 %"methodcall.3", %"trunc.1"
  %"needs_sep" = alloca i1
  store i1 %"netmp", i1* %"needs_sep"
  %"self_len.3" = load i64, i64* %"self_len"
  %"other_len.2" = load i64, i64* %"other_len"
  %"addtmp" = add i64 %"self_len.3", %"other_len.2"
  %"needs_sep.1" = load i1, i1* %"needs_sep"
  br i1 %"needs_sep.1", label %"then.3", label %"else.3"
then.3:
  br label %"ifcont.3"
else.3:
  br label %"ifcont.3"
ifcont.3:
  %"iftmp" = phi  i64 [1, %"then.3"], [0, %"else.3"]
  %"addtmp.1" = add i64 %"addtmp", %"iftmp"
  %"new_len" = alloca i64
  store i64 %"addtmp.1", i64* %"new_len"
  %"new_len.1" = load i64, i64* %"new_len"
  %"addtmp.2" = add i64 %"new_len.1", 1
  %"calltmp" = call i8* @"malloc"(i64 %"addtmp.2")
  %"is_not_null" = icmp ne i8* %"calltmp", null
  %"opt_flag" = insertvalue {i1, i8*} undef, i1 %"is_not_null", 0
  %"opt_val" = insertvalue {i1, i8*} %"opt_flag", i8* %"calltmp", 1
  %"is_some" = extractvalue {i1, i8*} %"opt_val", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %"opt_val", 1
  %"buf" = alloca i8*
  store i8* %"unwrapped", i8** %"buf"
  %"self.5" = load %"Path", %"Path"* %"self.1"
  %".30" = extractvalue %"Path" %"self.5", 0
  %"self_ptr" = alloca i8*
  store i8* %".30", i8** %"self_ptr"
  %"other.6" = load i8*, i8** %"other.1"
  %"other_ptr" = alloca i8*
  store i8* %"other.6", i8** %"other_ptr"
  %"buf.1" = load i8*, i8** %"buf"
  %"self_ptr.1" = load i8*, i8** %"self_ptr"
  %"self_len.4" = load i64, i64* %"self_len"
  %"calltmp.1" = call i8* @"memcpy"(i8* %"buf.1", i8* %"self_ptr.1", i64 %"self_len.4")
  %"self_len.5" = load i64, i64* %"self_len"
  %"offset" = alloca i64
  store i64 %"self_len.5", i64* %"offset"
  %"needs_sep.2" = load i1, i1* %"needs_sep"
  br i1 %"needs_sep.2", label %"then.4", label %"else.4"
if_let_else:
  %"self.6" = load %"Path", %"Path"* %"self.1"
  %".41" = extractvalue %"Path" %"self.6", 0
  %".42" = insertvalue %"Path" undef, i8* %".41", 0
  store %"Path" %".42", %"Path"* %"if_let_result"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp" = load %"Path", %"Path"* %"if_let_result"
  ret %"Path" %"if_let_tmp"
then.4:
  %"trunc.2" = trunc i64 47 to i8
  %"offset.1" = load i64, i64* %"offset"
  %"container" = load i8*, i8** %"buf"
  %"ptr_elem" = getelementptr i8, i8* %"container", i64 %"offset.1"
  store i8 %"trunc.2", i8* %"ptr_elem"
  %"offset.2" = load i64, i64* %"offset"
  %"addtmp.3" = add i64 %"offset.2", 1
  store i64 %"addtmp.3", i64* %"offset"
  br label %"ifcont.4"
else.4:
  br label %"ifcont.4"
ifcont.4:
  %"buf.2" = load i8*, i8** %"buf"
  %"offset.3" = load i64, i64* %"offset"
  %"ptr_add" = getelementptr i8, i8* %"buf.2", i64 %"offset.3"
  %"other_ptr.1" = load i8*, i8** %"other_ptr"
  %"other_len.3" = load i64, i64* %"other_len"
  %"calltmp.2" = call i8* @"memcpy"(i8* %"ptr_add", i8* %"other_ptr.1", i64 %"other_len.3")
  %"trunc.3" = trunc i64 0 to i8
  %"new_len.2" = load i64, i64* %"new_len"
  %"container.1" = load i8*, i8** %"buf"
  %"ptr_elem.1" = getelementptr i8, i8* %"container.1", i64 %"new_len.2"
  store i8 %"trunc.3", i8* %"ptr_elem.1"
  %"buf.3" = load i8*, i8** %"buf"
  %".40" = insertvalue %"Path" undef, i8* %"buf.3", 0
  store %"Path" %".40", %"Path"* %"if_let_result"
  br label %"if_let_merge"
}

define %"Path" @"Path_join_path"(%"Path" %"self", %"Path" %"other")
{
entry:
  %"self.1" = alloca %"Path"
  store %"Path" %"self", %"Path"* %"self.1"
  %"other.1" = alloca %"Path"
  store %"Path" %"other", %"Path"* %"other.1"
  %"self.2" = load %"Path", %"Path"* %"self.1"
  %"other.2" = load %"Path", %"Path"* %"other.1"
  %".6" = extractvalue %"Path" %"other.2", 0
  %"methodcall" = call %"Path" @"Path_join"(%"Path" %"self.2", i8* %".6")
  ret %"Path" %"methodcall"
}

define i1 @"Path_is_absolute"(%"Path" %"self")
{
entry:
  %"self.1" = alloca %"Path"
  store %"Path" %"self", %"Path"* %"self.1"
  %"self.2" = load %"Path", %"Path"* %"self.1"
  %".4" = extractvalue %"Path" %"self.2", 0
  %"methodcall" = call i64 @"String_len"(i8* %".4")
  %"len" = alloca i64
  store i64 %"methodcall", i64* %"len"
  %"len.1" = load i64, i64* %"len"
  %"eqtmp" = icmp eq i64 %"len.1", 0
  br i1 %"eqtmp", label %"then", label %"else"
then:
  ret i1 0
else:
  br label %"ifcont"
ifcont:
  %"self.3" = load %"Path", %"Path"* %"self.1"
  %".9" = extractvalue %"Path" %"self.3", 0
  %"methodcall.1" = call i8 @"String_byte_at"(i8* %".9", i64 0)
  %"trunc" = trunc i64 47 to i8
  %"eqtmp.1" = icmp eq i8 %"methodcall.1", %"trunc"
  ret i1 %"eqtmp.1"
}

define i1 @"Path_is_relative"(%"Path" %"self")
{
entry:
  %"self.1" = alloca %"Path"
  store %"Path" %"self", %"Path"* %"self.1"
  %"self.2" = load %"Path", %"Path"* %"self.1"
  %"methodcall" = call i1 @"Path_is_absolute"(%"Path" %"self.2")
  %"nottmp" = xor i1 %"methodcall", 1
  ret i1 %"nottmp"
}

define i1 @"Path_is_empty"(%"Path" %"self")
{
entry:
  %"self.1" = alloca %"Path"
  store %"Path" %"self", %"Path"* %"self.1"
  %"self.2" = load %"Path", %"Path"* %"self.1"
  %".4" = extractvalue %"Path" %"self.2", 0
  %"methodcall" = call i64 @"String_len"(i8* %".4")
  %"eqtmp" = icmp eq i64 %"methodcall", 0
  ret i1 %"eqtmp"
}

define i1 @"CommandOutput_success"(%"CommandOutput" %"self")
{
entry:
  %"self.1" = alloca %"CommandOutput"
  store %"CommandOutput" %"self", %"CommandOutput"* %"self.1"
  %"self.2" = load %"CommandOutput", %"CommandOutput"* %"self.1"
  %".4" = extractvalue %"CommandOutput" %"self.2", 1
  %"trunc" = trunc i64 0 to i32
  %"eqtmp" = icmp eq i32 %".4", %"trunc"
  ret i1 %"eqtmp"
}

define %"Command" @"Command_init_program"(i8* %"program")
{
entry:
  %"program.1" = alloca i8*
  store i8* %"program", i8** %"program.1"
  %"program.2" = load i8*, i8** %"program.1"
  %".4" = insertvalue {i1, i8*} undef, i1 0, 0
  %".5" = insertvalue %"Command" undef, i8* %"program.2", 0
  %".6" = insertvalue %"Command" %".5", {i1, i8*} %".4", 1
  %".7" = insertvalue %"Command" %".6", i64 0, 2
  %".8" = insertvalue %"Command" %".7", i64 0, 3
  ret %"Command" %".8"
}

define void @"Command_arg"(%"Command"* %"self", i8* %"argument")
{
entry:
  %"argument.1" = alloca i8*
  store i8* %"argument", i8** %"argument.1"
  %"self.1" = load %"Command", %"Command"* %"self"
  %"argument.2" = load i8*, i8** %"argument.1"
  call void @"Command_append_arg"(%"Command"* %"self", i8* %"argument.2")
  ret void
}

define void @"Command_append_arg"(%"Command"* %"self", i8* %"argument")
{
entry:
  %"argument.1" = alloca i8*
  store i8* %"argument", i8** %"argument.1"
  %"argument.2" = load i8*, i8** %"argument.1"
  %"arg_ptr" = alloca i8*
  store i8* %"argument.2", i8** %"arg_ptr"
  %"arg_ptr.1" = load i8*, i8** %"arg_ptr"
  %"calltmp" = call i64 @"strlen"(i8* %"arg_ptr.1")
  %"arg_len" = alloca i64
  store i64 %"calltmp", i64* %"arg_len"
  %"self.1" = load %"Command", %"Command"* %"self"
  %".7" = extractvalue %"Command" %"self.1", 2
  %"addtmp" = add i64 %".7", 1
  %"arg_len.1" = load i64, i64* %"arg_len"
  %"addtmp.1" = add i64 %"addtmp", %"arg_len.1"
  %"addtmp.2" = add i64 %"addtmp.1", 1
  %"needed" = alloca i64
  store i64 %"addtmp.2", i64* %"needed"
  %"self.2" = load %"Command", %"Command"* %"self"
  %".9" = extractvalue %"Command" %"self.2", 3
  %"needed.1" = load i64, i64* %"needed"
  %"lttmp" = icmp slt i64 %".9", %"needed.1"
  br i1 %"lttmp", label %"then", label %"else"
then:
  %"self.3" = load %"Command", %"Command"* %"self"
  %".11" = extractvalue %"Command" %"self.3", 3
  %"eqtmp" = icmp eq i64 %".11", 0
  br i1 %"eqtmp", label %"then.1", label %"else.1"
else:
  br label %"ifcont"
ifcont:
  %"self.6" = load %"Command", %"Command"* %"self"
  %".45" = extractvalue %"Command" %"self.6", 1
  %"is_some.3" = extractvalue {i1, i8*} %".45", 0
  br i1 %"is_some.3", label %"if_let_then.3", label %"if_let_else.3"
then.1:
  br label %"ifcont.1"
else.1:
  %"self.4" = load %"Command", %"Command"* %"self"
  %".13" = extractvalue %"Command" %"self.4", 3
  %"multmp" = mul i64 %".13", 2
  br label %"ifcont.1"
ifcont.1:
  %"iftmp" = phi  i64 [256, %"then.1"], [%"multmp", %"else.1"]
  %"new_cap" = alloca i64
  store i64 %"iftmp", i64* %"new_cap"
  br label %"while.cond"
while.cond:
  %"new_cap.1" = load i64, i64* %"new_cap"
  %"needed.2" = load i64, i64* %"needed"
  %"lttmp.1" = icmp slt i64 %"new_cap.1", %"needed.2"
  br i1 %"lttmp.1", label %"while.body", label %"while.end"
while.body:
  %"new_cap.2" = load i64, i64* %"new_cap"
  %"multmp.1" = mul i64 %"new_cap.2", 2
  store i64 %"multmp.1", i64* %"new_cap"
  br label %"while.cond"
while.end:
  %"self.5" = load %"Command", %"Command"* %"self"
  %".21" = extractvalue %"Command" %"self.5", 1
  %"is_some" = extractvalue {i1, i8*} %".21", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %".21", 1
  %"old_buf" = alloca i8*
  store i8* %"unwrapped", i8** %"old_buf"
  %"old_buf.1" = load i8*, i8** %"old_buf"
  %"new_cap.3" = load i64, i64* %"new_cap"
  %"calltmp.1" = call i8* @"realloc"(i8* %"old_buf.1", i64 %"new_cap.3")
  %"is_not_null" = icmp ne i8* %"calltmp.1", null
  %"opt_flag" = insertvalue {i1, i8*} undef, i1 %"is_not_null", 0
  %"opt_val" = insertvalue {i1, i8*} %"opt_flag", i8* %"calltmp.1", 1
  %"is_some.1" = extractvalue {i1, i8*} %"opt_val", 0
  br i1 %"is_some.1", label %"if_let_then.1", label %"if_let_else.1"
if_let_else:
  %"new_cap.5" = load i64, i64* %"new_cap"
  %"calltmp.2" = call i8* @"malloc"(i64 %"new_cap.5")
  %"is_not_null.1" = icmp ne i8* %"calltmp.2", null
  %"opt_flag.1" = insertvalue {i1, i8*} undef, i1 %"is_not_null.1", 0
  %"opt_val.1" = insertvalue {i1, i8*} %"opt_flag.1", i8* %"calltmp.2", 1
  %"is_some.2" = extractvalue {i1, i8*} %"opt_val.1", 0
  br i1 %"is_some.2", label %"if_let_then.2", label %"if_let_else.2"
if_let_merge:
  br label %"ifcont"
if_let_then.1:
  %"unwrapped.1" = extractvalue {i1, i8*} %"opt_val", 1
  %"new_buf" = alloca i8*
  store i8* %"unwrapped.1", i8** %"new_buf"
  %"new_buf.1" = load i8*, i8** %"new_buf"
  %"args_buffer_ptr" = getelementptr %"Command", %"Command"* %"self", i32 0, i32 1
  %".26" = insertvalue {i1, i8*} undef, i1 1, 0
  %".27" = insertvalue {i1, i8*} %".26", i8* %"new_buf.1", 1
  store {i1, i8*} %".27", {i1, i8*}* %"args_buffer_ptr"
  %"new_cap.4" = load i64, i64* %"new_cap"
  %"args_cap_ptr" = getelementptr %"Command", %"Command"* %"self", i32 0, i32 3
  store i64 %"new_cap.4", i64* %"args_cap_ptr"
  br label %"if_let_merge.1"
if_let_else.1:
  br label %"if_let_merge.1"
if_let_merge.1:
  br label %"if_let_merge"
if_let_then.2:
  %"unwrapped.2" = extractvalue {i1, i8*} %"opt_val.1", 1
  %"new_buf.2" = alloca i8*
  store i8* %"unwrapped.2", i8** %"new_buf.2"
  %"trunc" = trunc i64 0 to i8
  %"container" = load i8*, i8** %"new_buf.2"
  %"ptr_elem" = getelementptr i8, i8* %"container", i64 0
  store i8 %"trunc", i8* %"ptr_elem"
  %"new_buf.3" = load i8*, i8** %"new_buf.2"
  %"args_buffer_ptr.1" = getelementptr %"Command", %"Command"* %"self", i32 0, i32 1
  %".35" = insertvalue {i1, i8*} undef, i1 1, 0
  %".36" = insertvalue {i1, i8*} %".35", i8* %"new_buf.3", 1
  store {i1, i8*} %".36", {i1, i8*}* %"args_buffer_ptr.1"
  %"new_cap.6" = load i64, i64* %"new_cap"
  %"args_cap_ptr.1" = getelementptr %"Command", %"Command"* %"self", i32 0, i32 3
  store i64 %"new_cap.6", i64* %"args_cap_ptr.1"
  br label %"if_let_merge.2"
if_let_else.2:
  br label %"if_let_merge.2"
if_let_merge.2:
  br label %"if_let_merge"
if_let_then.3:
  %"unwrapped.3" = extractvalue {i1, i8*} %".45", 1
  %"buf" = alloca i8*
  store i8* %"unwrapped.3", i8** %"buf"
  %"self.7" = load %"Command", %"Command"* %"self"
  %".48" = extractvalue %"Command" %"self.7", 2
  %"gttmp" = icmp sgt i64 %".48", 0
  br i1 %"gttmp", label %"then.2", label %"else.2"
if_let_else.3:
  br label %"if_let_merge.3"
if_let_merge.3:
  ret void
then.2:
  %"trunc.1" = trunc i64 32 to i8
  %"self.8" = load %"Command", %"Command"* %"self"
  %".50" = extractvalue %"Command" %"self.8", 2
  %"container.1" = load i8*, i8** %"buf"
  %"ptr_elem.1" = getelementptr i8, i8* %"container.1", i64 %".50"
  store i8 %"trunc.1", i8* %"ptr_elem.1"
  %"self.9" = load %"Command", %"Command"* %"self"
  %".52" = extractvalue %"Command" %"self.9", 2
  %"addtmp.3" = add i64 %".52", 1
  %"args_len_ptr" = getelementptr %"Command", %"Command"* %"self", i32 0, i32 2
  store i64 %"addtmp.3", i64* %"args_len_ptr"
  br label %"ifcont.2"
else.2:
  br label %"ifcont.2"
ifcont.2:
  %"i" = alloca i64
  store i64 0, i64* %"i"
  br label %"while.cond.1"
while.cond.1:
  %"i.1" = load i64, i64* %"i"
  %"arg_len.2" = load i64, i64* %"arg_len"
  %"lttmp.2" = icmp slt i64 %"i.1", %"arg_len.2"
  br i1 %"lttmp.2", label %"while.body.1", label %"while.end.1"
while.body.1:
  %"arg_ptr.2" = load i8*, i8** %"arg_ptr"
  %"i.2" = load i64, i64* %"i"
  %"ptr_idx" = getelementptr i8, i8* %"arg_ptr.2", i64 %"i.2"
  %"ptr_elem.2" = load i8, i8* %"ptr_idx"
  %"self.10" = load %"Command", %"Command"* %"self"
  %".59" = extractvalue %"Command" %"self.10", 2
  %"i.3" = load i64, i64* %"i"
  %"addtmp.4" = add i64 %".59", %"i.3"
  %"container.2" = load i8*, i8** %"buf"
  %"ptr_elem.3" = getelementptr i8, i8* %"container.2", i64 %"addtmp.4"
  store i8 %"ptr_elem.2", i8* %"ptr_elem.3"
  %"i.4" = load i64, i64* %"i"
  %"addtmp.5" = add i64 %"i.4", 1
  store i64 %"addtmp.5", i64* %"i"
  br label %"while.cond.1"
while.end.1:
  %"self.11" = load %"Command", %"Command"* %"self"
  %".63" = extractvalue %"Command" %"self.11", 2
  %"arg_len.3" = load i64, i64* %"arg_len"
  %"addtmp.6" = add i64 %".63", %"arg_len.3"
  %"args_len_ptr.1" = getelementptr %"Command", %"Command"* %"self", i32 0, i32 2
  store i64 %"addtmp.6", i64* %"args_len_ptr.1"
  %"trunc.2" = trunc i64 0 to i8
  %"self.12" = load %"Command", %"Command"* %"self"
  %".65" = extractvalue %"Command" %"self.12", 2
  %"container.3" = load i8*, i8** %"buf"
  %"ptr_elem.4" = getelementptr i8, i8* %"container.3", i64 %".65"
  store i8 %"trunc.2", i8* %"ptr_elem.4"
  br label %"if_let_merge.3"
}

define i8* @"Command_build_command"(%"Command" %"self")
{
entry:
  %"if_let_result" = alloca i8*
  %"self.1" = alloca %"Command"
  store %"Command" %"self", %"Command"* %"self.1"
  %"self.2" = load %"Command", %"Command"* %"self.1"
  %".4" = extractvalue %"Command" %"self.2", 0
  %"prog_ptr" = alloca i8*
  store i8* %".4", i8** %"prog_ptr"
  %"prog_ptr.1" = load i8*, i8** %"prog_ptr"
  %"calltmp" = call i64 @"strlen"(i8* %"prog_ptr.1")
  %"prog_len" = alloca i64
  store i64 %"calltmp", i64* %"prog_len"
  %"prog_len.1" = load i64, i64* %"prog_len"
  %"total_len" = alloca i64
  store i64 %"prog_len.1", i64* %"total_len"
  %"self.3" = load %"Command", %"Command"* %"self.1"
  %".8" = extractvalue %"Command" %"self.3", 2
  %"gttmp" = icmp sgt i64 %".8", 0
  br i1 %"gttmp", label %"then", label %"else"
then:
  %"total_len.1" = load i64, i64* %"total_len"
  %"addtmp" = add i64 %"total_len.1", 1
  %"self.4" = load %"Command", %"Command"* %"self.1"
  %".10" = extractvalue %"Command" %"self.4", 2
  %"addtmp.1" = add i64 %"addtmp", %".10"
  store i64 %"addtmp.1", i64* %"total_len"
  br label %"ifcont"
else:
  br label %"ifcont"
ifcont:
  %"total_len.2" = load i64, i64* %"total_len"
  %"addtmp.2" = add i64 %"total_len.2", 1
  %"buf_size" = alloca i64
  store i64 %"addtmp.2", i64* %"buf_size"
  %"buf_size.1" = load i64, i64* %"buf_size"
  %"calltmp.1" = call i8* @"malloc"(i64 %"buf_size.1")
  %"is_not_null" = icmp ne i8* %"calltmp.1", null
  %"opt_flag" = insertvalue {i1, i8*} undef, i1 %"is_not_null", 0
  %"opt_val" = insertvalue {i1, i8*} %"opt_flag", i8* %"calltmp.1", 1
  %"is_some" = extractvalue {i1, i8*} %"opt_val", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %"opt_val", 1
  %"cmd_buf" = alloca i8*
  store i8* %"unwrapped", i8** %"cmd_buf"
  %"cmd_buf.1" = load i8*, i8** %"cmd_buf"
  %"prog_ptr.2" = load i8*, i8** %"prog_ptr"
  %"buf_size.2" = load i64, i64* %"buf_size"
  %"calltmp.2" = call i64 @"strlcpy"(i8* %"cmd_buf.1", i8* %"prog_ptr.2", i64 %"buf_size.2")
  %"self.5" = load %"Command", %"Command"* %"self.1"
  %".17" = extractvalue %"Command" %"self.5", 1
  %"is_some.1" = extractvalue {i1, i8*} %".17", 0
  br i1 %"is_some.1", label %"if_let_then.1", label %"if_let_else.1"
if_let_else:
  %"self.7" = load %"Command", %"Command"* %"self.1"
  %".28" = extractvalue %"Command" %"self.7", 0
  store i8* %".28", i8** %"if_let_result"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp" = load i8*, i8** %"if_let_result"
  ret i8* %"if_let_tmp"
if_let_then.1:
  %"unwrapped.1" = extractvalue {i1, i8*} %".17", 1
  %"args" = alloca i8*
  store i8* %"unwrapped.1", i8** %"args"
  %"self.6" = load %"Command", %"Command"* %"self.1"
  %".20" = extractvalue %"Command" %"self.6", 2
  %"gttmp.1" = icmp sgt i64 %".20", 0
  br i1 %"gttmp.1", label %"then.1", label %"else.1"
if_let_else.1:
  br label %"if_let_merge.1"
if_let_merge.1:
  %"cmd_buf.4" = load i8*, i8** %"cmd_buf"
  store i8* %"cmd_buf.4", i8** %"if_let_result"
  br label %"if_let_merge"
then.1:
  %".22" = getelementptr inbounds [2 x i8], [2 x i8]* @".str.3", i32 0, i32 0
  %"space" = alloca i8*
  store i8* %".22", i8** %"space"
  %"cmd_buf.2" = load i8*, i8** %"cmd_buf"
  %"space.1" = load i8*, i8** %"space"
  %"buf_size.3" = load i64, i64* %"buf_size"
  %"calltmp.3" = call i64 @"strlcat"(i8* %"cmd_buf.2", i8* %"space.1", i64 %"buf_size.3")
  %"cmd_buf.3" = load i8*, i8** %"cmd_buf"
  %"args.1" = load i8*, i8** %"args"
  %"buf_size.4" = load i64, i64* %"buf_size"
  %"calltmp.4" = call i64 @"strlcat"(i8* %"cmd_buf.3", i8* %"args.1", i64 %"buf_size.4")
  br label %"ifcont.1"
else.1:
  br label %"ifcont.1"
ifcont.1:
  br label %"if_let_merge.1"
}

define i32 @"Command_run"(%"Command" %"self")
{
entry:
  %"self.1" = alloca %"Command"
  store %"Command" %"self", %"Command"* %"self.1"
  %"self.2" = load %"Command", %"Command"* %"self.1"
  %"methodcall" = call i8* @"Command_build_command"(%"Command" %"self.2")
  %"cmd" = alloca i8*
  store i8* %"methodcall", i8** %"cmd"
  %"cmd.1" = load i8*, i8** %"cmd"
  %"cmd_ptr" = alloca i8*
  store i8* %"cmd.1", i8** %"cmd_ptr"
  %"cmd_ptr.1" = load i8*, i8** %"cmd_ptr"
  %"calltmp" = call i32 @"system"(i8* %"cmd_ptr.1")
  %"result" = alloca i32
  store i32 %"calltmp", i32* %"result"
  %"result.1" = load i32, i32* %"result"
  %"trunc" = trunc i64 256 to i32
  %"divtmp" = sdiv i32 %"result.1", %"trunc"
  ret i32 %"divtmp"
}

define {i1, %"CommandOutput"} @"Command_output"(%"Command" %"self")
{
entry:
  %"if_let_result.1" = alloca {i1, %"CommandOutput"}
  %"if_let_result" = alloca i8*
  %"self.1" = alloca %"Command"
  store %"Command" %"self", %"Command"* %"self.1"
  %"self.2" = load %"Command", %"Command"* %"self.1"
  %"methodcall" = call i8* @"Command_build_command"(%"Command" %"self.2")
  %"cmd" = alloca i8*
  store i8* %"methodcall", i8** %"cmd"
  %"cmd.1" = load i8*, i8** %"cmd"
  %"cmd_ptr" = alloca i8*
  store i8* %"cmd.1", i8** %"cmd_ptr"
  %".6" = getelementptr inbounds [2 x i8], [2 x i8]* @".str.4", i32 0, i32 0
  %"mode" = alloca i8*
  store i8* %".6", i8** %"mode"
  %"cmd_ptr.1" = load i8*, i8** %"cmd_ptr"
  %"mode.1" = load i8*, i8** %"mode"
  %"calltmp" = call i8* @"popen"(i8* %"cmd_ptr.1", i8* %"mode.1")
  %"is_not_null" = icmp ne i8* %"calltmp", null
  %"opt_flag" = insertvalue {i1, i8*} undef, i1 %"is_not_null", 0
  %"opt_val" = insertvalue {i1, i8*} %"opt_flag", i8* %"calltmp", 1
  %"is_some" = extractvalue {i1, i8*} %"opt_val", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %"opt_val", 1
  %"stream" = alloca i8*
  store i8* %"unwrapped", i8** %"stream"
  %".10" = insertvalue {i1, i8*} undef, i1 0, 0
  %"output_buf" = alloca {i1, i8*}
  store {i1, i8*} %".10", {i1, i8*}* %"output_buf"
  %"output_len" = alloca i64
  store i64 0, i64* %"output_len"
  %"output_cap" = alloca i64
  store i64 0, i64* %"output_cap"
  %"calltmp.1" = call i8* @"malloc"(i64 1024)
  %"is_not_null.1" = icmp ne i8* %"calltmp.1", null
  %"opt_flag.1" = insertvalue {i1, i8*} undef, i1 %"is_not_null.1", 0
  %"opt_val.1" = insertvalue {i1, i8*} %"opt_flag.1", i8* %"calltmp.1", 1
  %"is_some.1" = extractvalue {i1, i8*} %"opt_val.1", 0
  br i1 %"is_some.1", label %"if_let_then.1", label %"if_let_else.1"
if_let_else:
  %".89" = insertvalue {i1, %"CommandOutput"} undef, i1 0, 0
  store {i1, %"CommandOutput"} %".89", {i1, %"CommandOutput"}* %"if_let_result.1"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp.1" = load {i1, %"CommandOutput"}, {i1, %"CommandOutput"}* %"if_let_result.1"
  ret {i1, %"CommandOutput"} %"if_let_tmp.1"
if_let_then.1:
  %"unwrapped.1" = extractvalue {i1, i8*} %"opt_val.1", 1
  %"read_buf" = alloca i8*
  store i8* %"unwrapped.1", i8** %"read_buf"
  %"done" = alloca i1
  store i1 0, i1* %"done"
  br label %"while.cond"
if_let_else.1:
  br label %"if_let_merge.1"
if_let_merge.1:
  %"stream.3" = load i8*, i8** %"stream"
  %"calltmp.7" = call i32 @"pclose"(i8* %"stream.3")
  %"status" = alloca i32
  store i32 %"calltmp.7", i32* %"status"
  %"status.1" = load i32, i32* %"status"
  %"trunc.2" = trunc i64 256 to i32
  %"divtmp" = sdiv i32 %"status.1", %"trunc.2"
  %"exit_code" = alloca i32
  store i32 %"divtmp", i32* %"exit_code"
  %"output_buf.3" = load {i1, i8*}, {i1, i8*}* %"output_buf"
  %"is_some.6" = extractvalue {i1, i8*} %"output_buf.3", 0
  br i1 %"is_some.6", label %"if_let_then.6", label %"if_let_else.6"
while.cond:
  %"done.1" = load i1, i1* %"done"
  %"nottmp" = xor i1 %"done.1", 1
  br i1 %"nottmp", label %"while.body", label %"while.end"
while.body:
  %"read_buf.1" = load i8*, i8** %"read_buf"
  %"stream.1" = load i8*, i8** %"stream"
  %"calltmp.2" = call i64 @"fread"(i8* %"read_buf.1", i64 1, i64 1024, i8* %"stream.1")
  %"bytes_read" = alloca i64
  store i64 %"calltmp.2", i64* %"bytes_read"
  %"bytes_read.1" = load i64, i64* %"bytes_read"
  %"gttmp" = icmp sgt i64 %"bytes_read.1", 0
  br i1 %"gttmp", label %"then", label %"else"
while.end:
  %"read_buf.3" = load i8*, i8** %"read_buf"
  call void @"free"(i8* %"read_buf.3")
  br label %"if_let_merge.1"
then:
  %"output_len.1" = load i64, i64* %"output_len"
  %"bytes_read.2" = load i64, i64* %"bytes_read"
  %"addtmp" = add i64 %"output_len.1", %"bytes_read.2"
  %"addtmp.1" = add i64 %"addtmp", 1
  %"needed" = alloca i64
  store i64 %"addtmp.1", i64* %"needed"
  %"output_cap.1" = load i64, i64* %"output_cap"
  %"needed.1" = load i64, i64* %"needed"
  %"lttmp" = icmp slt i64 %"output_cap.1", %"needed.1"
  br i1 %"lttmp", label %"then.1", label %"else.1"
else:
  br label %"ifcont"
ifcont:
  %"stream.2" = load i8*, i8** %"stream"
  %"calltmp.5" = call i32 @"feof"(i8* %"stream.2")
  %"trunc.1" = trunc i64 0 to i32
  %"netmp" = icmp ne i32 %"calltmp.5", %"trunc.1"
  br i1 %"netmp", label %"or_merge", label %"or_right"
then.1:
  %"output_cap.2" = load i64, i64* %"output_cap"
  %"eqtmp" = icmp eq i64 %"output_cap.2", 0
  br i1 %"eqtmp", label %"then.2", label %"else.2"
else.1:
  br label %"ifcont.1"
ifcont.1:
  %"output_buf.2" = load {i1, i8*}, {i1, i8*}* %"output_buf"
  %"is_some.5" = extractvalue {i1, i8*} %"output_buf.2", 0
  br i1 %"is_some.5", label %"if_let_then.5", label %"if_let_else.5"
then.2:
  br label %"ifcont.2"
else.2:
  %"output_cap.3" = load i64, i64* %"output_cap"
  %"multmp" = mul i64 %"output_cap.3", 2
  br label %"ifcont.2"
ifcont.2:
  %"iftmp" = phi  i64 [1024, %"then.2"], [%"multmp", %"else.2"]
  %"new_cap" = alloca i64
  store i64 %"iftmp", i64* %"new_cap"
  br label %"while.cond.1"
while.cond.1:
  %"new_cap.1" = load i64, i64* %"new_cap"
  %"needed.2" = load i64, i64* %"needed"
  %"lttmp.1" = icmp slt i64 %"new_cap.1", %"needed.2"
  br i1 %"lttmp.1", label %"while.body.1", label %"while.end.1"
while.body.1:
  %"new_cap.2" = load i64, i64* %"new_cap"
  %"multmp.1" = mul i64 %"new_cap.2", 2
  store i64 %"multmp.1", i64* %"new_cap"
  br label %"while.cond.1"
while.end.1:
  %"output_buf.1" = load {i1, i8*}, {i1, i8*}* %"output_buf"
  %"is_some.2" = extractvalue {i1, i8*} %"output_buf.1", 0
  br i1 %"is_some.2", label %"if_let_then.2", label %"if_let_else.2"
if_let_then.2:
  %"unwrapped.2" = extractvalue {i1, i8*} %"output_buf.1", 1
  %"old" = alloca i8*
  store i8* %"unwrapped.2", i8** %"old"
  %"old.1" = load i8*, i8** %"old"
  %"new_cap.3" = load i64, i64* %"new_cap"
  %"calltmp.3" = call i8* @"realloc"(i8* %"old.1", i64 %"new_cap.3")
  %"is_not_null.2" = icmp ne i8* %"calltmp.3", null
  %"opt_flag.2" = insertvalue {i1, i8*} undef, i1 %"is_not_null.2", 0
  %"opt_val.2" = insertvalue {i1, i8*} %"opt_flag.2", i8* %"calltmp.3", 1
  %"is_some.3" = extractvalue {i1, i8*} %"opt_val.2", 0
  br i1 %"is_some.3", label %"if_let_then.3", label %"if_let_else.3"
if_let_else.2:
  %"new_cap.5" = load i64, i64* %"new_cap"
  %"calltmp.4" = call i8* @"malloc"(i64 %"new_cap.5")
  %"is_not_null.3" = icmp ne i8* %"calltmp.4", null
  %"opt_flag.3" = insertvalue {i1, i8*} undef, i1 %"is_not_null.3", 0
  %"opt_val.3" = insertvalue {i1, i8*} %"opt_flag.3", i8* %"calltmp.4", 1
  %"is_some.4" = extractvalue {i1, i8*} %"opt_val.3", 0
  br i1 %"is_some.4", label %"if_let_then.4", label %"if_let_else.4"
if_let_merge.2:
  br label %"ifcont.1"
if_let_then.3:
  %"unwrapped.3" = extractvalue {i1, i8*} %"opt_val.2", 1
  %"new_buf" = alloca i8*
  store i8* %"unwrapped.3", i8** %"new_buf"
  %"new_buf.1" = load i8*, i8** %"new_buf"
  %".35" = insertvalue {i1, i8*} undef, i1 1, 0
  %".36" = insertvalue {i1, i8*} %".35", i8* %"new_buf.1", 1
  store {i1, i8*} %".36", {i1, i8*}* %"output_buf"
  %"new_cap.4" = load i64, i64* %"new_cap"
  store i64 %"new_cap.4", i64* %"output_cap"
  br label %"if_let_merge.3"
if_let_else.3:
  br label %"if_let_merge.3"
if_let_merge.3:
  br label %"if_let_merge.2"
if_let_then.4:
  %"unwrapped.4" = extractvalue {i1, i8*} %"opt_val.3", 1
  %"new_buf.2" = alloca i8*
  store i8* %"unwrapped.4", i8** %"new_buf.2"
  %"new_buf.3" = load i8*, i8** %"new_buf.2"
  %".43" = insertvalue {i1, i8*} undef, i1 1, 0
  %".44" = insertvalue {i1, i8*} %".43", i8* %"new_buf.3", 1
  store {i1, i8*} %".44", {i1, i8*}* %"output_buf"
  %"new_cap.6" = load i64, i64* %"new_cap"
  store i64 %"new_cap.6", i64* %"output_cap"
  br label %"if_let_merge.4"
if_let_else.4:
  br label %"if_let_merge.4"
if_let_merge.4:
  br label %"if_let_merge.2"
if_let_then.5:
  %"unwrapped.5" = extractvalue {i1, i8*} %"output_buf.2", 1
  %"out" = alloca i8*
  store i8* %"unwrapped.5", i8** %"out"
  %"i" = alloca i64
  store i64 0, i64* %"i"
  br label %"while.cond.2"
if_let_else.5:
  br label %"if_let_merge.5"
if_let_merge.5:
  br label %"ifcont"
while.cond.2:
  %"i.1" = load i64, i64* %"i"
  %"bytes_read.3" = load i64, i64* %"bytes_read"
  %"lttmp.2" = icmp slt i64 %"i.1", %"bytes_read.3"
  br i1 %"lttmp.2", label %"while.body.2", label %"while.end.2"
while.body.2:
  %"read_buf.2" = load i8*, i8** %"read_buf"
  %"i.2" = load i64, i64* %"i"
  %"ptr_idx" = getelementptr i8, i8* %"read_buf.2", i64 %"i.2"
  %"ptr_elem" = load i8, i8* %"ptr_idx"
  %"output_len.2" = load i64, i64* %"output_len"
  %"i.3" = load i64, i64* %"i"
  %"addtmp.2" = add i64 %"output_len.2", %"i.3"
  %"container" = load i8*, i8** %"out"
  %"ptr_elem.1" = getelementptr i8, i8* %"container", i64 %"addtmp.2"
  store i8 %"ptr_elem", i8* %"ptr_elem.1"
  %"i.4" = load i64, i64* %"i"
  %"addtmp.3" = add i64 %"i.4", 1
  store i64 %"addtmp.3", i64* %"i"
  br label %"while.cond.2"
while.end.2:
  %"output_len.3" = load i64, i64* %"output_len"
  %"bytes_read.4" = load i64, i64* %"bytes_read"
  %"addtmp.4" = add i64 %"output_len.3", %"bytes_read.4"
  store i64 %"addtmp.4", i64* %"output_len"
  %"trunc" = trunc i64 0 to i8
  %"output_len.4" = load i64, i64* %"output_len"
  %"container.1" = load i8*, i8** %"out"
  %"ptr_elem.2" = getelementptr i8, i8* %"container.1", i64 %"output_len.4"
  store i8 %"trunc", i8* %"ptr_elem.2"
  br label %"if_let_merge.5"
or_right:
  %"bytes_read.5" = load i64, i64* %"bytes_read"
  %"eqtmp.1" = icmp eq i64 %"bytes_read.5", 0
  br label %"or_merge"
or_merge:
  %"or_result" = phi  i1 [1, %"ifcont"], [%"eqtmp.1", %"or_right"]
  br i1 %"or_result", label %"then.3", label %"else.3"
then.3:
  store i1 1, i1* %"done"
  br label %"ifcont.3"
else.3:
  br label %"ifcont.3"
ifcont.3:
  br label %"while.cond"
if_let_then.6:
  %"unwrapped.6" = extractvalue {i1, i8*} %"output_buf.3", 1
  %"out.1" = alloca i8*
  store i8* %"unwrapped.6", i8** %"out.1"
  %"out.2" = load i8*, i8** %"out.1"
  %"s" = alloca i8*
  store i8* %"out.2", i8** %"s"
  %"out.3" = load i8*, i8** %"out.1"
  call void @"free"(i8* %"out.3")
  %"s.1" = load i8*, i8** %"s"
  store i8* %"s.1", i8** %"if_let_result"
  br label %"if_let_merge.6"
if_let_else.6:
  %".81" = getelementptr inbounds [1 x i8], [1 x i8]* @".str.5", i32 0, i32 0
  store i8* %".81", i8** %"if_let_result"
  br label %"if_let_merge.6"
if_let_merge.6:
  %"if_let_tmp" = load i8*, i8** %"if_let_result"
  %"stdout_str" = alloca i8*
  store i8* %"if_let_tmp", i8** %"stdout_str"
  %"stdout_str.1" = load i8*, i8** %"stdout_str"
  %"exit_code.1" = load i32, i32* %"exit_code"
  %".87" = insertvalue %"CommandOutput" undef, i8* %"stdout_str.1", 0
  %".88" = insertvalue %"CommandOutput" %".87", i32 %"exit_code.1", 1
  %".90" = insertvalue {i1, %"CommandOutput"} undef, i1 1, 0
  %"some_then" = insertvalue {i1, %"CommandOutput"} %".90", %"CommandOutput" %".88", 1
  store {i1, %"CommandOutput"} %"some_then", {i1, %"CommandOutput"}* %"if_let_result.1"
  br label %"if_let_merge"
}

define void @"Command_deinit"(%"Command"* %"self")
{
entry:
  %"self.1" = load %"Command", %"Command"* %"self"
  %".3" = extractvalue %"Command" %"self.1", 1
  %"is_some" = extractvalue {i1, i8*} %".3", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %".3", 1
  %"buf" = alloca i8*
  store i8* %"unwrapped", i8** %"buf"
  %"buf.1" = load i8*, i8** %"buf"
  call void @"free"(i8* %"buf.1")
  br label %"if_let_merge"
if_let_else:
  br label %"if_let_merge"
if_let_merge:
  ret void
}

define i64 @"String_len"(i8* %"self")
{
entry:
  %"self.1" = alloca i8*
  store i8* %"self", i8** %"self.1"
  %"self.2" = load i8*, i8** %"self.1"
  %"ptr" = alloca i8*
  store i8* %"self.2", i8** %"ptr"
  %"ptr.1" = load i8*, i8** %"ptr"
  %"calltmp" = call i64 @"strlen"(i8* %"ptr.1")
  ret i64 %"calltmp"
}

define i1 @"String_is_empty"(i8* %"self")
{
entry:
  %"self.1" = alloca i8*
  store i8* %"self", i8** %"self.1"
  %"self.2" = load i8*, i8** %"self.1"
  %"methodcall" = call i64 @"String_len"(i8* %"self.2")
  %"eqtmp" = icmp eq i64 %"methodcall", 0
  ret i1 %"eqtmp"
}

define i8 @"String_byte_at"(i8* %"self", i64 %"index")
{
entry:
  %"self.1" = alloca i8*
  store i8* %"self", i8** %"self.1"
  %"index.1" = alloca i64
  store i64 %"index", i64* %"index.1"
  %"self.2" = load i8*, i8** %"self.1"
  %"ptr" = alloca i8*
  store i8* %"self.2", i8** %"ptr"
  %"ptr.1" = load i8*, i8** %"ptr"
  %"index.2" = load i64, i64* %"index.1"
  %"ptr_idx" = getelementptr i8, i8* %"ptr.1", i64 %"index.2"
  %"ptr_elem" = load i8, i8* %"ptr_idx"
  ret i8 %"ptr_elem"
}

define i1 @"String_starts_with"(i8* %"self", i8* %"prefix")
{
entry:
  %"self.1" = alloca i8*
  store i8* %"self", i8** %"self.1"
  %"prefix.1" = alloca i8*
  store i8* %"prefix", i8** %"prefix.1"
  %"self.2" = load i8*, i8** %"self.1"
  %"methodcall" = call i64 @"String_len"(i8* %"self.2")
  %"self_len" = alloca i64
  store i64 %"methodcall", i64* %"self_len"
  %"prefix.2" = load i8*, i8** %"prefix.1"
  %"methodcall.1" = call i64 @"String_len"(i8* %"prefix.2")
  %"prefix_len" = alloca i64
  store i64 %"methodcall.1", i64* %"prefix_len"
  %"prefix_len.1" = load i64, i64* %"prefix_len"
  %"self_len.1" = load i64, i64* %"self_len"
  %"gttmp" = icmp sgt i64 %"prefix_len.1", %"self_len.1"
  br i1 %"gttmp", label %"then", label %"else"
then:
  br label %"ifcont"
else:
  %"i" = alloca i64
  store i64 0, i64* %"i"
  %"matches" = alloca i1
  store i1 1, i1* %"matches"
  br label %"while.cond"
ifcont:
  %"iftmp" = phi  i1 [0, %"then"], [%"matches.2", %"while.end"]
  ret i1 %"iftmp"
while.cond:
  %"i.1" = load i64, i64* %"i"
  %"prefix_len.2" = load i64, i64* %"prefix_len"
  %"lttmp" = icmp slt i64 %"i.1", %"prefix_len.2"
  br i1 %"lttmp", label %"and_right", label %"and_merge"
while.body:
  %"self.3" = load i8*, i8** %"self.1"
  %"i.2" = load i64, i64* %"i"
  %"methodcall.2" = call i8 @"String_byte_at"(i8* %"self.3", i64 %"i.2")
  %"prefix.3" = load i8*, i8** %"prefix.1"
  %"i.3" = load i64, i64* %"i"
  %"methodcall.3" = call i8 @"String_byte_at"(i8* %"prefix.3", i64 %"i.3")
  %"netmp" = icmp ne i8 %"methodcall.2", %"methodcall.3"
  br i1 %"netmp", label %"then.1", label %"else.1"
while.end:
  %"matches.2" = load i1, i1* %"matches"
  br label %"ifcont"
and_right:
  %"matches.1" = load i1, i1* %"matches"
  br label %"and_merge"
and_merge:
  %"and_result" = phi  i1 [0, %"while.cond"], [%"matches.1", %"and_right"]
  br i1 %"and_result", label %"while.body", label %"while.end"
then.1:
  store i1 0, i1* %"matches"
  br label %"ifcont.1"
else.1:
  br label %"ifcont.1"
ifcont.1:
  %"i.4" = load i64, i64* %"i"
  %"addtmp" = add i64 %"i.4", 1
  store i64 %"addtmp", i64* %"i"
  br label %"while.cond"
}

define i1 @"String_ends_with"(i8* %"self", i8* %"suffix")
{
entry:
  %"self.1" = alloca i8*
  store i8* %"self", i8** %"self.1"
  %"suffix.1" = alloca i8*
  store i8* %"suffix", i8** %"suffix.1"
  %"self.2" = load i8*, i8** %"self.1"
  %"methodcall" = call i64 @"String_len"(i8* %"self.2")
  %"self_len" = alloca i64
  store i64 %"methodcall", i64* %"self_len"
  %"suffix.2" = load i8*, i8** %"suffix.1"
  %"methodcall.1" = call i64 @"String_len"(i8* %"suffix.2")
  %"suffix_len" = alloca i64
  store i64 %"methodcall.1", i64* %"suffix_len"
  %"suffix_len.1" = load i64, i64* %"suffix_len"
  %"self_len.1" = load i64, i64* %"self_len"
  %"gttmp" = icmp sgt i64 %"suffix_len.1", %"self_len.1"
  br i1 %"gttmp", label %"then", label %"else"
then:
  br label %"ifcont"
else:
  %"self_len.2" = load i64, i64* %"self_len"
  %"suffix_len.2" = load i64, i64* %"suffix_len"
  %"subtmp" = sub i64 %"self_len.2", %"suffix_len.2"
  %"offset" = alloca i64
  store i64 %"subtmp", i64* %"offset"
  %"i" = alloca i64
  store i64 0, i64* %"i"
  %"matches" = alloca i1
  store i1 1, i1* %"matches"
  br label %"while.cond"
ifcont:
  %"iftmp" = phi  i1 [0, %"then"], [%"matches.2", %"while.end"]
  ret i1 %"iftmp"
while.cond:
  %"i.1" = load i64, i64* %"i"
  %"suffix_len.3" = load i64, i64* %"suffix_len"
  %"lttmp" = icmp slt i64 %"i.1", %"suffix_len.3"
  br i1 %"lttmp", label %"and_right", label %"and_merge"
while.body:
  %"self.3" = load i8*, i8** %"self.1"
  %"offset.1" = load i64, i64* %"offset"
  %"i.2" = load i64, i64* %"i"
  %"addtmp" = add i64 %"offset.1", %"i.2"
  %"methodcall.2" = call i8 @"String_byte_at"(i8* %"self.3", i64 %"addtmp")
  %"suffix.3" = load i8*, i8** %"suffix.1"
  %"i.3" = load i64, i64* %"i"
  %"methodcall.3" = call i8 @"String_byte_at"(i8* %"suffix.3", i64 %"i.3")
  %"netmp" = icmp ne i8 %"methodcall.2", %"methodcall.3"
  br i1 %"netmp", label %"then.1", label %"else.1"
while.end:
  %"matches.2" = load i1, i1* %"matches"
  br label %"ifcont"
and_right:
  %"matches.1" = load i1, i1* %"matches"
  br label %"and_merge"
and_merge:
  %"and_result" = phi  i1 [0, %"while.cond"], [%"matches.1", %"and_right"]
  br i1 %"and_result", label %"while.body", label %"while.end"
then.1:
  store i1 0, i1* %"matches"
  br label %"ifcont.1"
else.1:
  br label %"ifcont.1"
ifcont.1:
  %"i.4" = load i64, i64* %"i"
  %"addtmp.1" = add i64 %"i.4", 1
  store i64 %"addtmp.1", i64* %"i"
  br label %"while.cond"
}

define i1 @"String_contains"(i8* %"self", i8* %"needle")
{
entry:
  %"self.1" = alloca i8*
  store i8* %"self", i8** %"self.1"
  %"needle.1" = alloca i8*
  store i8* %"needle", i8** %"needle.1"
  %"self.2" = load i8*, i8** %"self.1"
  %"methodcall" = call i64 @"String_len"(i8* %"self.2")
  %"self_len" = alloca i64
  store i64 %"methodcall", i64* %"self_len"
  %"needle.2" = load i8*, i8** %"needle.1"
  %"methodcall.1" = call i64 @"String_len"(i8* %"needle.2")
  %"needle_len" = alloca i64
  store i64 %"methodcall.1", i64* %"needle_len"
  %"needle_len.1" = load i64, i64* %"needle_len"
  %"eqtmp" = icmp eq i64 %"needle_len.1", 0
  br i1 %"eqtmp", label %"then", label %"else"
then:
  br label %"ifcont"
else:
  %"needle_len.2" = load i64, i64* %"needle_len"
  %"self_len.1" = load i64, i64* %"self_len"
  %"gttmp" = icmp sgt i64 %"needle_len.2", %"self_len.1"
  br i1 %"gttmp", label %"then.1", label %"else.1"
ifcont:
  %"iftmp.1" = phi  i1 [1, %"then"], [%"iftmp", %"ifcont.1"]
  ret i1 %"iftmp.1"
then.1:
  br label %"ifcont.1"
else.1:
  %"found" = alloca i1
  store i1 0, i1* %"found"
  %"i" = alloca i64
  store i64 0, i64* %"i"
  br label %"while.cond"
ifcont.1:
  %"iftmp" = phi  i1 [0, %"then.1"], [%"found.2", %"while.end"]
  br label %"ifcont"
while.cond:
  %"i.1" = load i64, i64* %"i"
  %"self_len.2" = load i64, i64* %"self_len"
  %"needle_len.3" = load i64, i64* %"needle_len"
  %"subtmp" = sub i64 %"self_len.2", %"needle_len.3"
  %"letmp" = icmp sle i64 %"i.1", %"subtmp"
  br i1 %"letmp", label %"and_right", label %"and_merge"
while.body:
  %"j" = alloca i64
  store i64 0, i64* %"j"
  %"matches" = alloca i1
  store i1 1, i1* %"matches"
  br label %"while.cond.1"
while.end:
  %"found.2" = load i1, i1* %"found"
  br label %"ifcont.1"
and_right:
  %"found.1" = load i1, i1* %"found"
  %"nottmp" = xor i1 %"found.1", 1
  br label %"and_merge"
and_merge:
  %"and_result" = phi  i1 [0, %"while.cond"], [%"nottmp", %"and_right"]
  br i1 %"and_result", label %"while.body", label %"while.end"
while.cond.1:
  %"j.1" = load i64, i64* %"j"
  %"needle_len.4" = load i64, i64* %"needle_len"
  %"lttmp" = icmp slt i64 %"j.1", %"needle_len.4"
  br i1 %"lttmp", label %"and_right.1", label %"and_merge.1"
while.body.1:
  %"self.3" = load i8*, i8** %"self.1"
  %"i.2" = load i64, i64* %"i"
  %"j.2" = load i64, i64* %"j"
  %"addtmp" = add i64 %"i.2", %"j.2"
  %"methodcall.2" = call i8 @"String_byte_at"(i8* %"self.3", i64 %"addtmp")
  %"needle.3" = load i8*, i8** %"needle.1"
  %"j.3" = load i64, i64* %"j"
  %"methodcall.3" = call i8 @"String_byte_at"(i8* %"needle.3", i64 %"j.3")
  %"netmp" = icmp ne i8 %"methodcall.2", %"methodcall.3"
  br i1 %"netmp", label %"then.2", label %"else.2"
while.end.1:
  %"matches.2" = load i1, i1* %"matches"
  br i1 %"matches.2", label %"then.3", label %"else.3"
and_right.1:
  %"matches.1" = load i1, i1* %"matches"
  br label %"and_merge.1"
and_merge.1:
  %"and_result.1" = phi  i1 [0, %"while.cond.1"], [%"matches.1", %"and_right.1"]
  br i1 %"and_result.1", label %"while.body.1", label %"while.end.1"
then.2:
  store i1 0, i1* %"matches"
  br label %"ifcont.2"
else.2:
  br label %"ifcont.2"
ifcont.2:
  %"j.4" = load i64, i64* %"j"
  %"addtmp.1" = add i64 %"j.4", 1
  store i64 %"addtmp.1", i64* %"j"
  br label %"while.cond.1"
then.3:
  store i1 1, i1* %"found"
  br label %"ifcont.3"
else.3:
  br label %"ifcont.3"
ifcont.3:
  %"i.3" = load i64, i64* %"i"
  %"addtmp.2" = add i64 %"i.3", 1
  store i64 %"addtmp.2", i64* %"i"
  br label %"while.cond"
}

define i1 @"String__is_whitespace"(i8* %"self", i8 %"b")
{
entry:
  %"self.1" = alloca i8*
  store i8* %"self", i8** %"self.1"
  %"b.1" = alloca i8
  store i8 %"b", i8* %"b.1"
  %"b.2" = load i8, i8* %"b.1"
  %"trunc" = trunc i64 32 to i8
  %"eqtmp" = icmp eq i8 %"b.2", %"trunc"
  br i1 %"eqtmp", label %"or_merge.2", label %"or_right.2"
or_right:
  %"b.5" = load i8, i8* %"b.1"
  %"trunc.3" = trunc i64 13 to i8
  %"eqtmp.3" = icmp eq i8 %"b.5", %"trunc.3"
  br label %"or_merge"
or_merge:
  %"or_result.2" = phi  i1 [1, %"or_merge.1"], [%"eqtmp.3", %"or_right"]
  ret i1 %"or_result.2"
or_right.1:
  %"b.4" = load i8, i8* %"b.1"
  %"trunc.2" = trunc i64 10 to i8
  %"eqtmp.2" = icmp eq i8 %"b.4", %"trunc.2"
  br label %"or_merge.1"
or_merge.1:
  %"or_result.1" = phi  i1 [1, %"or_merge.2"], [%"eqtmp.2", %"or_right.1"]
  br i1 %"or_result.1", label %"or_merge", label %"or_right"
or_right.2:
  %"b.3" = load i8, i8* %"b.1"
  %"trunc.1" = trunc i64 9 to i8
  %"eqtmp.1" = icmp eq i8 %"b.3", %"trunc.1"
  br label %"or_merge.2"
or_merge.2:
  %"or_result" = phi  i1 [1, %"entry"], [%"eqtmp.1", %"or_right.2"]
  br i1 %"or_result", label %"or_merge.1", label %"or_right.1"
}

define i8* @"String_trim_start"(i8* %"self")
{
entry:
  %"self.1" = alloca i8*
  store i8* %"self", i8** %"self.1"
  %"self.2" = load i8*, i8** %"self.1"
  %"methodcall" = call i64 @"String_len"(i8* %"self.2")
  %"len" = alloca i64
  store i64 %"methodcall", i64* %"len"
  %"len.1" = load i64, i64* %"len"
  %"eqtmp" = icmp eq i64 %"len.1", 0
  br i1 %"eqtmp", label %"then", label %"else"
then:
  %"self.3" = load i8*, i8** %"self.1"
  br label %"ifcont"
else:
  %"start" = alloca i64
  store i64 0, i64* %"start"
  br label %"while.cond"
ifcont:
  %"iftmp.2" = phi  i8* [%"self.3", %"then"], [%"iftmp.1", %"ifcont.1"]
  ret i8* %"iftmp.2"
while.cond:
  %"start.1" = load i64, i64* %"start"
  %"len.2" = load i64, i64* %"len"
  %"lttmp" = icmp slt i64 %"start.1", %"len.2"
  br i1 %"lttmp", label %"and_right", label %"and_merge"
while.body:
  %"start.3" = load i64, i64* %"start"
  %"addtmp" = add i64 %"start.3", 1
  store i64 %"addtmp", i64* %"start"
  br label %"while.cond"
while.end:
  %"start.4" = load i64, i64* %"start"
  %"eqtmp.1" = icmp eq i64 %"start.4", 0
  br i1 %"eqtmp.1", label %"then.1", label %"else.1"
and_right:
  %"self.4" = load i8*, i8** %"self.1"
  %"self.5" = load i8*, i8** %"self.1"
  %"start.2" = load i64, i64* %"start"
  %"methodcall.1" = call i8 @"String_byte_at"(i8* %"self.5", i64 %"start.2")
  %"methodcall.2" = call i1 @"String__is_whitespace"(i8* %"self.4", i8 %"methodcall.1")
  br label %"and_merge"
and_merge:
  %"and_result" = phi  i1 [0, %"while.cond"], [%"methodcall.2", %"and_right"]
  br i1 %"and_result", label %"while.body", label %"while.end"
then.1:
  %"self.6" = load i8*, i8** %"self.1"
  br label %"ifcont.1"
else.1:
  %"start.5" = load i64, i64* %"start"
  %"len.3" = load i64, i64* %"len"
  %"eqtmp.2" = icmp eq i64 %"start.5", %"len.3"
  br i1 %"eqtmp.2", label %"then.2", label %"else.2"
ifcont.1:
  %"iftmp.1" = phi  i8* [%"self.6", %"then.1"], [%"iftmp", %"ifcont.2"]
  br label %"ifcont"
then.2:
  %".15" = getelementptr inbounds [1 x i8], [1 x i8]* @".str.5", i32 0, i32 0
  br label %"ifcont.2"
else.2:
  %"self.7" = load i8*, i8** %"self.1"
  %"start.6" = load i64, i64* %"start"
  %"len.4" = load i64, i64* %"len"
  %"start.7" = load i64, i64* %"start"
  %"subtmp" = sub i64 %"len.4", %"start.7"
  %"methodcall.3" = call i8* @"String__substring"(i8* %"self.7", i64 %"start.6", i64 %"subtmp")
  br label %"ifcont.2"
ifcont.2:
  %"iftmp" = phi  i8* [%".15", %"then.2"], [%"methodcall.3", %"else.2"]
  br label %"ifcont.1"
}

define i8* @"String_trim_end"(i8* %"self")
{
entry:
  %"self.1" = alloca i8*
  store i8* %"self", i8** %"self.1"
  %"self.2" = load i8*, i8** %"self.1"
  %"methodcall" = call i64 @"String_len"(i8* %"self.2")
  %"len" = alloca i64
  store i64 %"methodcall", i64* %"len"
  %"len.1" = load i64, i64* %"len"
  %"eqtmp" = icmp eq i64 %"len.1", 0
  br i1 %"eqtmp", label %"then", label %"else"
then:
  %"self.3" = load i8*, i8** %"self.1"
  br label %"ifcont"
else:
  %"len.2" = load i64, i64* %"len"
  %"end" = alloca i64
  store i64 %"len.2", i64* %"end"
  br label %"while.cond"
ifcont:
  %"iftmp.2" = phi  i8* [%"self.3", %"then"], [%"iftmp.1", %"ifcont.1"]
  ret i8* %"iftmp.2"
while.cond:
  %"end.1" = load i64, i64* %"end"
  %"gttmp" = icmp sgt i64 %"end.1", 0
  br i1 %"gttmp", label %"and_right", label %"and_merge"
while.body:
  %"end.3" = load i64, i64* %"end"
  %"subtmp.1" = sub i64 %"end.3", 1
  store i64 %"subtmp.1", i64* %"end"
  br label %"while.cond"
while.end:
  %"end.4" = load i64, i64* %"end"
  %"len.3" = load i64, i64* %"len"
  %"eqtmp.1" = icmp eq i64 %"end.4", %"len.3"
  br i1 %"eqtmp.1", label %"then.1", label %"else.1"
and_right:
  %"self.4" = load i8*, i8** %"self.1"
  %"self.5" = load i8*, i8** %"self.1"
  %"end.2" = load i64, i64* %"end"
  %"subtmp" = sub i64 %"end.2", 1
  %"methodcall.1" = call i8 @"String_byte_at"(i8* %"self.5", i64 %"subtmp")
  %"methodcall.2" = call i1 @"String__is_whitespace"(i8* %"self.4", i8 %"methodcall.1")
  br label %"and_merge"
and_merge:
  %"and_result" = phi  i1 [0, %"while.cond"], [%"methodcall.2", %"and_right"]
  br i1 %"and_result", label %"while.body", label %"while.end"
then.1:
  %"self.6" = load i8*, i8** %"self.1"
  br label %"ifcont.1"
else.1:
  %"end.5" = load i64, i64* %"end"
  %"eqtmp.2" = icmp eq i64 %"end.5", 0
  br i1 %"eqtmp.2", label %"then.2", label %"else.2"
ifcont.1:
  %"iftmp.1" = phi  i8* [%"self.6", %"then.1"], [%"iftmp", %"ifcont.2"]
  br label %"ifcont"
then.2:
  %".15" = getelementptr inbounds [1 x i8], [1 x i8]* @".str.5", i32 0, i32 0
  br label %"ifcont.2"
else.2:
  %"self.7" = load i8*, i8** %"self.1"
  %"end.6" = load i64, i64* %"end"
  %"methodcall.3" = call i8* @"String__substring"(i8* %"self.7", i64 0, i64 %"end.6")
  br label %"ifcont.2"
ifcont.2:
  %"iftmp" = phi  i8* [%".15", %"then.2"], [%"methodcall.3", %"else.2"]
  br label %"ifcont.1"
}

define i8* @"String_trim"(i8* %"self")
{
entry:
  %"self.1" = alloca i8*
  store i8* %"self", i8** %"self.1"
  %"self.2" = load i8*, i8** %"self.1"
  %"methodcall" = call i8* @"String_trim_start"(i8* %"self.2")
  %"methodcall.1" = call i8* @"String_trim_end"(i8* %"methodcall")
  ret i8* %"methodcall.1"
}

define i8* @"String__substring"(i8* %"self", i64 %"start", i64 %"length")
{
entry:
  %"if_let_result" = alloca i8*
  %"self.1" = alloca i8*
  store i8* %"self", i8** %"self.1"
  %"start.1" = alloca i64
  store i64 %"start", i64* %"start.1"
  %"length.1" = alloca i64
  store i64 %"length", i64* %"length.1"
  %"length.2" = load i64, i64* %"length.1"
  %"letmp" = icmp sle i64 %"length.2", 0
  br i1 %"letmp", label %"then", label %"else"
then:
  %".9" = getelementptr inbounds [1 x i8], [1 x i8]* @".str.5", i32 0, i32 0
  br label %"ifcont"
else:
  %"length.3" = load i64, i64* %"length.1"
  %"addtmp" = add i64 %"length.3", 1
  %"calltmp" = call i8* @"malloc"(i64 %"addtmp")
  %"is_not_null" = icmp ne i8* %"calltmp", null
  %"opt_flag" = insertvalue {i1, i8*} undef, i1 %"is_not_null", 0
  %"opt_val" = insertvalue {i1, i8*} %"opt_flag", i8* %"calltmp", 1
  %"is_some" = extractvalue {i1, i8*} %"opt_val", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
ifcont:
  %"iftmp" = phi  i8* [%".9", %"then"], [%"if_let_tmp", %"if_let_merge"]
  ret i8* %"iftmp"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %"opt_val", 1
  %"new_ptr" = alloca i8*
  store i8* %"unwrapped", i8** %"new_ptr"
  %"i" = alloca i64
  store i64 0, i64* %"i"
  br label %"while.cond"
if_let_else:
  %".19" = getelementptr inbounds [1 x i8], [1 x i8]* @".str.5", i32 0, i32 0
  store i8* %".19", i8** %"if_let_result"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp" = load i8*, i8** %"if_let_result"
  br label %"ifcont"
while.cond:
  %"i.1" = load i64, i64* %"i"
  %"length.4" = load i64, i64* %"length.1"
  %"lttmp" = icmp slt i64 %"i.1", %"length.4"
  br i1 %"lttmp", label %"while.body", label %"while.end"
while.body:
  %"self.2" = load i8*, i8** %"self.1"
  %"start.2" = load i64, i64* %"start.1"
  %"i.2" = load i64, i64* %"i"
  %"addtmp.1" = add i64 %"start.2", %"i.2"
  %"methodcall" = call i8 @"String_byte_at"(i8* %"self.2", i64 %"addtmp.1")
  %"i.3" = load i64, i64* %"i"
  %"container" = load i8*, i8** %"new_ptr"
  %"ptr_elem" = getelementptr i8, i8* %"container", i64 %"i.3"
  store i8 %"methodcall", i8* %"ptr_elem"
  %"i.4" = load i64, i64* %"i"
  %"addtmp.2" = add i64 %"i.4", 1
  store i64 %"addtmp.2", i64* %"i"
  br label %"while.cond"
while.end:
  %"trunc" = trunc i64 0 to i8
  %"length.5" = load i64, i64* %"length.1"
  %"container.1" = load i8*, i8** %"new_ptr"
  %"ptr_elem.1" = getelementptr i8, i8* %"container.1", i64 %"length.5"
  store i8 %"trunc", i8* %"ptr_elem.1"
  %"new_ptr.1" = load i8*, i8** %"new_ptr"
  store i8* %"new_ptr.1", i8** %"if_let_result"
  br label %"if_let_merge"
}

define i8* @"String_to_uppercase"(i8* %"self")
{
entry:
  %"if_let_result" = alloca i8*
  %"self.1" = alloca i8*
  store i8* %"self", i8** %"self.1"
  %"self.2" = load i8*, i8** %"self.1"
  %"methodcall" = call i64 @"String_len"(i8* %"self.2")
  %"len" = alloca i64
  store i64 %"methodcall", i64* %"len"
  %"len.1" = load i64, i64* %"len"
  %"eqtmp" = icmp eq i64 %"len.1", 0
  br i1 %"eqtmp", label %"then", label %"else"
then:
  %"self.3" = load i8*, i8** %"self.1"
  br label %"ifcont"
else:
  %"len.2" = load i64, i64* %"len"
  %"addtmp" = add i64 %"len.2", 1
  %"calltmp" = call i8* @"malloc"(i64 %"addtmp")
  %"is_not_null" = icmp ne i8* %"calltmp", null
  %"opt_flag" = insertvalue {i1, i8*} undef, i1 %"is_not_null", 0
  %"opt_val" = insertvalue {i1, i8*} %"opt_flag", i8* %"calltmp", 1
  %"is_some" = extractvalue {i1, i8*} %"opt_val", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
ifcont:
  %"iftmp" = phi  i8* [%"self.3", %"then"], [%"if_let_tmp", %"if_let_merge"]
  ret i8* %"iftmp"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %"opt_val", 1
  %"new_ptr" = alloca i8*
  store i8* %"unwrapped", i8** %"new_ptr"
  %"i" = alloca i64
  store i64 0, i64* %"i"
  br label %"while.cond"
if_let_else:
  %"self.5" = load i8*, i8** %"self.1"
  store i8* %"self.5", i8** %"if_let_result"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp" = load i8*, i8** %"if_let_result"
  br label %"ifcont"
while.cond:
  %"i.1" = load i64, i64* %"i"
  %"len.3" = load i64, i64* %"len"
  %"lttmp" = icmp slt i64 %"i.1", %"len.3"
  br i1 %"lttmp", label %"while.body", label %"while.end"
while.body:
  %"self.4" = load i8*, i8** %"self.1"
  %"i.2" = load i64, i64* %"i"
  %"methodcall.1" = call i8 @"String_byte_at"(i8* %"self.4", i64 %"i.2")
  %"c" = alloca i8
  store i8 %"methodcall.1", i8* %"c"
  %"c.1" = load i8, i8* %"c"
  %"trunc" = trunc i64 97 to i8
  %"getmp" = icmp sge i8 %"c.1", %"trunc"
  br i1 %"getmp", label %"and_right", label %"and_merge"
while.end:
  %"trunc.3" = trunc i64 0 to i8
  %"len.4" = load i64, i64* %"len"
  %"container.2" = load i8*, i8** %"new_ptr"
  %"ptr_elem.2" = getelementptr i8, i8* %"container.2", i64 %"len.4"
  store i8 %"trunc.3", i8* %"ptr_elem.2"
  %"new_ptr.1" = load i8*, i8** %"new_ptr"
  store i8* %"new_ptr.1", i8** %"if_let_result"
  br label %"if_let_merge"
and_right:
  %"c.2" = load i8, i8* %"c"
  %"trunc.1" = trunc i64 122 to i8
  %"letmp" = icmp sle i8 %"c.2", %"trunc.1"
  br label %"and_merge"
and_merge:
  %"and_result" = phi  i1 [0, %"while.body"], [%"letmp", %"and_right"]
  br i1 %"and_result", label %"then.1", label %"else.1"
then.1:
  %"c.3" = load i8, i8* %"c"
  %"trunc.2" = trunc i64 32 to i8
  %"subtmp" = sub i8 %"c.3", %"trunc.2"
  %"i.3" = load i64, i64* %"i"
  %"container" = load i8*, i8** %"new_ptr"
  %"ptr_elem" = getelementptr i8, i8* %"container", i64 %"i.3"
  store i8 %"subtmp", i8* %"ptr_elem"
  br label %"ifcont.1"
else.1:
  %"c.4" = load i8, i8* %"c"
  %"i.4" = load i64, i64* %"i"
  %"container.1" = load i8*, i8** %"new_ptr"
  %"ptr_elem.1" = getelementptr i8, i8* %"container.1", i64 %"i.4"
  store i8 %"c.4", i8* %"ptr_elem.1"
  br label %"ifcont.1"
ifcont.1:
  %"i.5" = load i64, i64* %"i"
  %"addtmp.1" = add i64 %"i.5", 1
  store i64 %"addtmp.1", i64* %"i"
  br label %"while.cond"
}

define i8* @"String_to_lowercase"(i8* %"self")
{
entry:
  %"if_let_result" = alloca i8*
  %"self.1" = alloca i8*
  store i8* %"self", i8** %"self.1"
  %"self.2" = load i8*, i8** %"self.1"
  %"methodcall" = call i64 @"String_len"(i8* %"self.2")
  %"len" = alloca i64
  store i64 %"methodcall", i64* %"len"
  %"len.1" = load i64, i64* %"len"
  %"eqtmp" = icmp eq i64 %"len.1", 0
  br i1 %"eqtmp", label %"then", label %"else"
then:
  %"self.3" = load i8*, i8** %"self.1"
  br label %"ifcont"
else:
  %"len.2" = load i64, i64* %"len"
  %"addtmp" = add i64 %"len.2", 1
  %"calltmp" = call i8* @"malloc"(i64 %"addtmp")
  %"is_not_null" = icmp ne i8* %"calltmp", null
  %"opt_flag" = insertvalue {i1, i8*} undef, i1 %"is_not_null", 0
  %"opt_val" = insertvalue {i1, i8*} %"opt_flag", i8* %"calltmp", 1
  %"is_some" = extractvalue {i1, i8*} %"opt_val", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
ifcont:
  %"iftmp" = phi  i8* [%"self.3", %"then"], [%"if_let_tmp", %"if_let_merge"]
  ret i8* %"iftmp"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %"opt_val", 1
  %"new_ptr" = alloca i8*
  store i8* %"unwrapped", i8** %"new_ptr"
  %"i" = alloca i64
  store i64 0, i64* %"i"
  br label %"while.cond"
if_let_else:
  %"self.5" = load i8*, i8** %"self.1"
  store i8* %"self.5", i8** %"if_let_result"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp" = load i8*, i8** %"if_let_result"
  br label %"ifcont"
while.cond:
  %"i.1" = load i64, i64* %"i"
  %"len.3" = load i64, i64* %"len"
  %"lttmp" = icmp slt i64 %"i.1", %"len.3"
  br i1 %"lttmp", label %"while.body", label %"while.end"
while.body:
  %"self.4" = load i8*, i8** %"self.1"
  %"i.2" = load i64, i64* %"i"
  %"methodcall.1" = call i8 @"String_byte_at"(i8* %"self.4", i64 %"i.2")
  %"c" = alloca i8
  store i8 %"methodcall.1", i8* %"c"
  %"c.1" = load i8, i8* %"c"
  %"trunc" = trunc i64 65 to i8
  %"getmp" = icmp sge i8 %"c.1", %"trunc"
  br i1 %"getmp", label %"and_right", label %"and_merge"
while.end:
  %"trunc.3" = trunc i64 0 to i8
  %"len.4" = load i64, i64* %"len"
  %"container.2" = load i8*, i8** %"new_ptr"
  %"ptr_elem.2" = getelementptr i8, i8* %"container.2", i64 %"len.4"
  store i8 %"trunc.3", i8* %"ptr_elem.2"
  %"new_ptr.1" = load i8*, i8** %"new_ptr"
  store i8* %"new_ptr.1", i8** %"if_let_result"
  br label %"if_let_merge"
and_right:
  %"c.2" = load i8, i8* %"c"
  %"trunc.1" = trunc i64 90 to i8
  %"letmp" = icmp sle i8 %"c.2", %"trunc.1"
  br label %"and_merge"
and_merge:
  %"and_result" = phi  i1 [0, %"while.body"], [%"letmp", %"and_right"]
  br i1 %"and_result", label %"then.1", label %"else.1"
then.1:
  %"c.3" = load i8, i8* %"c"
  %"trunc.2" = trunc i64 32 to i8
  %"addtmp.1" = add i8 %"c.3", %"trunc.2"
  %"i.3" = load i64, i64* %"i"
  %"container" = load i8*, i8** %"new_ptr"
  %"ptr_elem" = getelementptr i8, i8* %"container", i64 %"i.3"
  store i8 %"addtmp.1", i8* %"ptr_elem"
  br label %"ifcont.1"
else.1:
  %"c.4" = load i8, i8* %"c"
  %"i.4" = load i64, i64* %"i"
  %"container.1" = load i8*, i8** %"new_ptr"
  %"ptr_elem.1" = getelementptr i8, i8* %"container.1", i64 %"i.4"
  store i8 %"c.4", i8* %"ptr_elem.1"
  br label %"ifcont.1"
ifcont.1:
  %"i.5" = load i64, i64* %"i"
  %"addtmp.2" = add i64 %"i.5", 1
  store i64 %"addtmp.2", i64* %"i"
  br label %"while.cond"
}

define i8* @"String_replace"(i8* %"self", i8* %"old", i8* %"new")
{
entry:
  %"if_let_result" = alloca i8*
  %"self.1" = alloca i8*
  store i8* %"self", i8** %"self.1"
  %"old.1" = alloca i8*
  store i8* %"old", i8** %"old.1"
  %"new.1" = alloca i8*
  store i8* %"new", i8** %"new.1"
  %"self.2" = load i8*, i8** %"self.1"
  %"methodcall" = call i64 @"String_len"(i8* %"self.2")
  %"self_len" = alloca i64
  store i64 %"methodcall", i64* %"self_len"
  %"old.2" = load i8*, i8** %"old.1"
  %"methodcall.1" = call i64 @"String_len"(i8* %"old.2")
  %"old_len" = alloca i64
  store i64 %"methodcall.1", i64* %"old_len"
  %"new.2" = load i8*, i8** %"new.1"
  %"methodcall.2" = call i64 @"String_len"(i8* %"new.2")
  %"new_len" = alloca i64
  store i64 %"methodcall.2", i64* %"new_len"
  %"old_len.1" = load i64, i64* %"old_len"
  %"eqtmp" = icmp eq i64 %"old_len.1", 0
  br i1 %"eqtmp", label %"or_merge", label %"or_right"
or_right:
  %"self_len.1" = load i64, i64* %"self_len"
  %"eqtmp.1" = icmp eq i64 %"self_len.1", 0
  br label %"or_merge"
or_merge:
  %"or_result" = phi  i1 [1, %"entry"], [%"eqtmp.1", %"or_right"]
  br i1 %"or_result", label %"then", label %"else"
then:
  %"self.3" = load i8*, i8** %"self.1"
  br label %"ifcont"
else:
  %"count" = alloca i64
  store i64 0, i64* %"count"
  %"i" = alloca i64
  store i64 0, i64* %"i"
  br label %"while.cond"
ifcont:
  %"iftmp.1" = phi  i8* [%"self.3", %"then"], [%"iftmp", %"ifcont.3"]
  ret i8* %"iftmp.1"
while.cond:
  %"i.1" = load i64, i64* %"i"
  %"self_len.2" = load i64, i64* %"self_len"
  %"old_len.2" = load i64, i64* %"old_len"
  %"subtmp" = sub i64 %"self_len.2", %"old_len.2"
  %"letmp" = icmp sle i64 %"i.1", %"subtmp"
  br i1 %"letmp", label %"while.body", label %"while.end"
while.body:
  %"j" = alloca i64
  store i64 0, i64* %"j"
  %"matches" = alloca i1
  store i1 1, i1* %"matches"
  br label %"while.cond.1"
while.end:
  %"count.2" = load i64, i64* %"count"
  %"eqtmp.2" = icmp eq i64 %"count.2", 0
  br i1 %"eqtmp.2", label %"then.3", label %"else.3"
while.cond.1:
  %"j.1" = load i64, i64* %"j"
  %"old_len.3" = load i64, i64* %"old_len"
  %"lttmp" = icmp slt i64 %"j.1", %"old_len.3"
  br i1 %"lttmp", label %"and_right", label %"and_merge"
while.body.1:
  %"self.4" = load i8*, i8** %"self.1"
  %"i.2" = load i64, i64* %"i"
  %"j.2" = load i64, i64* %"j"
  %"addtmp" = add i64 %"i.2", %"j.2"
  %"methodcall.3" = call i8 @"String_byte_at"(i8* %"self.4", i64 %"addtmp")
  %"old.3" = load i8*, i8** %"old.1"
  %"j.3" = load i64, i64* %"j"
  %"methodcall.4" = call i8 @"String_byte_at"(i8* %"old.3", i64 %"j.3")
  %"netmp" = icmp ne i8 %"methodcall.3", %"methodcall.4"
  br i1 %"netmp", label %"then.1", label %"else.1"
while.end.1:
  %"matches.2" = load i1, i1* %"matches"
  br i1 %"matches.2", label %"then.2", label %"else.2"
and_right:
  %"matches.1" = load i1, i1* %"matches"
  br label %"and_merge"
and_merge:
  %"and_result" = phi  i1 [0, %"while.cond.1"], [%"matches.1", %"and_right"]
  br i1 %"and_result", label %"while.body.1", label %"while.end.1"
then.1:
  store i1 0, i1* %"matches"
  br label %"ifcont.1"
else.1:
  br label %"ifcont.1"
ifcont.1:
  %"j.4" = load i64, i64* %"j"
  %"addtmp.1" = add i64 %"j.4", 1
  store i64 %"addtmp.1", i64* %"j"
  br label %"while.cond.1"
then.2:
  %"count.1" = load i64, i64* %"count"
  %"addtmp.2" = add i64 %"count.1", 1
  store i64 %"addtmp.2", i64* %"count"
  %"i.3" = load i64, i64* %"i"
  %"old_len.4" = load i64, i64* %"old_len"
  %"addtmp.3" = add i64 %"i.3", %"old_len.4"
  store i64 %"addtmp.3", i64* %"i"
  br label %"ifcont.2"
else.2:
  %"i.4" = load i64, i64* %"i"
  %"addtmp.4" = add i64 %"i.4", 1
  store i64 %"addtmp.4", i64* %"i"
  br label %"ifcont.2"
ifcont.2:
  br label %"while.cond"
then.3:
  %"self.5" = load i8*, i8** %"self.1"
  br label %"ifcont.3"
else.3:
  %"self_len.3" = load i64, i64* %"self_len"
  %"count.3" = load i64, i64* %"count"
  %"old_len.5" = load i64, i64* %"old_len"
  %"multmp" = mul i64 %"count.3", %"old_len.5"
  %"subtmp.1" = sub i64 %"self_len.3", %"multmp"
  %"count.4" = load i64, i64* %"count"
  %"new_len.1" = load i64, i64* %"new_len"
  %"multmp.1" = mul i64 %"count.4", %"new_len.1"
  %"addtmp.5" = add i64 %"subtmp.1", %"multmp.1"
  %"new_size" = alloca i64
  store i64 %"addtmp.5", i64* %"new_size"
  %"new_size.1" = load i64, i64* %"new_size"
  %"addtmp.6" = add i64 %"new_size.1", 1
  %"calltmp" = call i8* @"malloc"(i64 %"addtmp.6")
  %"is_not_null" = icmp ne i8* %"calltmp", null
  %"opt_flag" = insertvalue {i1, i8*} undef, i1 %"is_not_null", 0
  %"opt_val" = insertvalue {i1, i8*} %"opt_flag", i8* %"calltmp", 1
  %"is_some" = extractvalue {i1, i8*} %"opt_val", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
ifcont.3:
  %"iftmp" = phi  i8* [%"self.5", %"then.3"], [%"if_let_tmp", %"if_let_merge"]
  br label %"ifcont"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %"opt_val", 1
  %"new_ptr" = alloca i8*
  store i8* %"unwrapped", i8** %"new_ptr"
  %"src_i" = alloca i64
  store i64 0, i64* %"src_i"
  %"dst_i" = alloca i64
  store i64 0, i64* %"dst_i"
  br label %"while.cond.2"
if_let_else:
  %"self.8" = load i8*, i8** %"self.1"
  store i8* %"self.8", i8** %"if_let_result"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp" = load i8*, i8** %"if_let_result"
  br label %"ifcont.3"
while.cond.2:
  %"src_i.1" = load i64, i64* %"src_i"
  %"self_len.4" = load i64, i64* %"self_len"
  %"lttmp.1" = icmp slt i64 %"src_i.1", %"self_len.4"
  br i1 %"lttmp.1", label %"while.body.2", label %"while.end.2"
while.body.2:
  %"matches.3" = alloca i1
  store i1 0, i1* %"matches.3"
  %"src_i.2" = load i64, i64* %"src_i"
  %"self_len.5" = load i64, i64* %"self_len"
  %"old_len.6" = load i64, i64* %"old_len"
  %"subtmp.2" = sub i64 %"self_len.5", %"old_len.6"
  %"letmp.1" = icmp sle i64 %"src_i.2", %"subtmp.2"
  br i1 %"letmp.1", label %"then.4", label %"else.4"
while.end.2:
  %"trunc" = trunc i64 0 to i8
  %"new_size.2" = load i64, i64* %"new_size"
  %"container.2" = load i8*, i8** %"new_ptr"
  %"ptr_elem.2" = getelementptr i8, i8* %"container.2", i64 %"new_size.2"
  store i8 %"trunc", i8* %"ptr_elem.2"
  %"new_ptr.1" = load i8*, i8** %"new_ptr"
  store i8* %"new_ptr.1", i8** %"if_let_result"
  br label %"if_let_merge"
then.4:
  store i1 1, i1* %"matches.3"
  %"j.5" = alloca i64
  store i64 0, i64* %"j.5"
  br label %"while.cond.3"
else.4:
  br label %"ifcont.4"
ifcont.4:
  %"matches.5" = load i1, i1* %"matches.3"
  br i1 %"matches.5", label %"then.6", label %"else.6"
while.cond.3:
  %"j.6" = load i64, i64* %"j.5"
  %"old_len.7" = load i64, i64* %"old_len"
  %"lttmp.2" = icmp slt i64 %"j.6", %"old_len.7"
  br i1 %"lttmp.2", label %"and_right.1", label %"and_merge.1"
while.body.3:
  %"self.6" = load i8*, i8** %"self.1"
  %"src_i.3" = load i64, i64* %"src_i"
  %"j.7" = load i64, i64* %"j.5"
  %"addtmp.7" = add i64 %"src_i.3", %"j.7"
  %"methodcall.5" = call i8 @"String_byte_at"(i8* %"self.6", i64 %"addtmp.7")
  %"old.4" = load i8*, i8** %"old.1"
  %"j.8" = load i64, i64* %"j.5"
  %"methodcall.6" = call i8 @"String_byte_at"(i8* %"old.4", i64 %"j.8")
  %"netmp.1" = icmp ne i8 %"methodcall.5", %"methodcall.6"
  br i1 %"netmp.1", label %"then.5", label %"else.5"
while.end.3:
  br label %"ifcont.4"
and_right.1:
  %"matches.4" = load i1, i1* %"matches.3"
  br label %"and_merge.1"
and_merge.1:
  %"and_result.1" = phi  i1 [0, %"while.cond.3"], [%"matches.4", %"and_right.1"]
  br i1 %"and_result.1", label %"while.body.3", label %"while.end.3"
then.5:
  store i1 0, i1* %"matches.3"
  br label %"ifcont.5"
else.5:
  br label %"ifcont.5"
ifcont.5:
  %"j.9" = load i64, i64* %"j.5"
  %"addtmp.8" = add i64 %"j.9", 1
  store i64 %"addtmp.8", i64* %"j.5"
  br label %"while.cond.3"
then.6:
  %"k" = alloca i64
  store i64 0, i64* %"k"
  br label %"while.cond.4"
else.6:
  %"self.7" = load i8*, i8** %"self.1"
  %"src_i.5" = load i64, i64* %"src_i"
  %"methodcall.8" = call i8 @"String_byte_at"(i8* %"self.7", i64 %"src_i.5")
  %"dst_i.3" = load i64, i64* %"dst_i"
  %"container.1" = load i8*, i8** %"new_ptr"
  %"ptr_elem.1" = getelementptr i8, i8* %"container.1", i64 %"dst_i.3"
  store i8 %"methodcall.8", i8* %"ptr_elem.1"
  %"dst_i.4" = load i64, i64* %"dst_i"
  %"addtmp.12" = add i64 %"dst_i.4", 1
  store i64 %"addtmp.12", i64* %"dst_i"
  %"src_i.6" = load i64, i64* %"src_i"
  %"addtmp.13" = add i64 %"src_i.6", 1
  store i64 %"addtmp.13", i64* %"src_i"
  br label %"ifcont.6"
ifcont.6:
  br label %"while.cond.2"
while.cond.4:
  %"k.1" = load i64, i64* %"k"
  %"new_len.2" = load i64, i64* %"new_len"
  %"lttmp.3" = icmp slt i64 %"k.1", %"new_len.2"
  br i1 %"lttmp.3", label %"while.body.4", label %"while.end.4"
while.body.4:
  %"new.3" = load i8*, i8** %"new.1"
  %"k.2" = load i64, i64* %"k"
  %"methodcall.7" = call i8 @"String_byte_at"(i8* %"new.3", i64 %"k.2")
  %"dst_i.1" = load i64, i64* %"dst_i"
  %"container" = load i8*, i8** %"new_ptr"
  %"ptr_elem" = getelementptr i8, i8* %"container", i64 %"dst_i.1"
  store i8 %"methodcall.7", i8* %"ptr_elem"
  %"dst_i.2" = load i64, i64* %"dst_i"
  %"addtmp.9" = add i64 %"dst_i.2", 1
  store i64 %"addtmp.9", i64* %"dst_i"
  %"k.3" = load i64, i64* %"k"
  %"addtmp.10" = add i64 %"k.3", 1
  store i64 %"addtmp.10", i64* %"k"
  br label %"while.cond.4"
while.end.4:
  %"src_i.4" = load i64, i64* %"src_i"
  %"old_len.8" = load i64, i64* %"old_len"
  %"addtmp.11" = add i64 %"src_i.4", %"old_len.8"
  store i64 %"addtmp.11", i64* %"src_i"
  br label %"ifcont.6"
}

define i1 @"String_equals"(i8* %"self", i8* %"other")
{
entry:
  %"self.1" = alloca i8*
  store i8* %"self", i8** %"self.1"
  %"other.1" = alloca i8*
  store i8* %"other", i8** %"other.1"
  %"self.2" = load i8*, i8** %"self.1"
  %"methodcall" = call i64 @"String_len"(i8* %"self.2")
  %"self_len" = alloca i64
  store i64 %"methodcall", i64* %"self_len"
  %"other.2" = load i8*, i8** %"other.1"
  %"methodcall.1" = call i64 @"String_len"(i8* %"other.2")
  %"other_len" = alloca i64
  store i64 %"methodcall.1", i64* %"other_len"
  %"self_len.1" = load i64, i64* %"self_len"
  %"other_len.1" = load i64, i64* %"other_len"
  %"netmp" = icmp ne i64 %"self_len.1", %"other_len.1"
  br i1 %"netmp", label %"then", label %"else"
then:
  br label %"ifcont"
else:
  %"i" = alloca i64
  store i64 0, i64* %"i"
  %"equal" = alloca i1
  store i1 1, i1* %"equal"
  br label %"while.cond"
ifcont:
  %"iftmp" = phi  i1 [0, %"then"], [%"equal.2", %"while.end"]
  ret i1 %"iftmp"
while.cond:
  %"i.1" = load i64, i64* %"i"
  %"self_len.2" = load i64, i64* %"self_len"
  %"lttmp" = icmp slt i64 %"i.1", %"self_len.2"
  br i1 %"lttmp", label %"and_right", label %"and_merge"
while.body:
  %"self.3" = load i8*, i8** %"self.1"
  %"i.2" = load i64, i64* %"i"
  %"methodcall.2" = call i8 @"String_byte_at"(i8* %"self.3", i64 %"i.2")
  %"other.3" = load i8*, i8** %"other.1"
  %"i.3" = load i64, i64* %"i"
  %"methodcall.3" = call i8 @"String_byte_at"(i8* %"other.3", i64 %"i.3")
  %"netmp.1" = icmp ne i8 %"methodcall.2", %"methodcall.3"
  br i1 %"netmp.1", label %"then.1", label %"else.1"
while.end:
  %"equal.2" = load i1, i1* %"equal"
  br label %"ifcont"
and_right:
  %"equal.1" = load i1, i1* %"equal"
  br label %"and_merge"
and_merge:
  %"and_result" = phi  i1 [0, %"while.cond"], [%"equal.1", %"and_right"]
  br i1 %"and_result", label %"while.body", label %"while.end"
then.1:
  store i1 0, i1* %"equal"
  br label %"ifcont.1"
else.1:
  br label %"ifcont.1"
ifcont.1:
  %"i.4" = load i64, i64* %"i"
  %"addtmp" = add i64 %"i.4", 1
  store i64 %"addtmp", i64* %"i"
  br label %"while.cond"
}

define i8* @"String_substring"(i8* %"self", i64 %"start", i64 %"end")
{
entry:
  %"self.1" = alloca i8*
  store i8* %"self", i8** %"self.1"
  %"start.1" = alloca i64
  store i64 %"start", i64* %"start.1"
  %"end.1" = alloca i64
  store i64 %"end", i64* %"end.1"
  %"self.2" = load i8*, i8** %"self.1"
  %"methodcall" = call i64 @"String_len"(i8* %"self.2")
  %"len" = alloca i64
  store i64 %"methodcall", i64* %"len"
  %"start.2" = load i64, i64* %"start.1"
  %"s" = alloca i64
  store i64 %"start.2", i64* %"s"
  %"end.2" = load i64, i64* %"end.1"
  %"e" = alloca i64
  store i64 %"end.2", i64* %"e"
  %"s.1" = load i64, i64* %"s"
  %"lttmp" = icmp slt i64 %"s.1", 0
  br i1 %"lttmp", label %"then", label %"else"
then:
  store i64 0, i64* %"s"
  br label %"ifcont"
else:
  br label %"ifcont"
ifcont:
  %"e.1" = load i64, i64* %"e"
  %"len.1" = load i64, i64* %"len"
  %"gttmp" = icmp sgt i64 %"e.1", %"len.1"
  br i1 %"gttmp", label %"then.1", label %"else.1"
then.1:
  %"len.2" = load i64, i64* %"len"
  store i64 %"len.2", i64* %"e"
  br label %"ifcont.1"
else.1:
  br label %"ifcont.1"
ifcont.1:
  %"s.2" = load i64, i64* %"s"
  %"e.2" = load i64, i64* %"e"
  %"getmp" = icmp sge i64 %"s.2", %"e.2"
  br i1 %"getmp", label %"then.2", label %"else.2"
then.2:
  %".20" = getelementptr inbounds [1 x i8], [1 x i8]* @".str.5", i32 0, i32 0
  ret i8* %".20"
else.2:
  br label %"ifcont.2"
ifcont.2:
  %"self.3" = load i8*, i8** %"self.1"
  %"s.3" = load i64, i64* %"s"
  %"e.3" = load i64, i64* %"e"
  %"s.4" = load i64, i64* %"s"
  %"subtmp" = sub i64 %"e.3", %"s.4"
  %"methodcall.1" = call i8* @"String__substring"(i8* %"self.3", i64 %"s.3", i64 %"subtmp")
  ret i8* %"methodcall.1"
}

define {i1, i64} @"String_index_of_char"(i8* %"self", i8 %"c")
{
entry:
  %"self.1" = alloca i8*
  store i8* %"self", i8** %"self.1"
  %"c.1" = alloca i8
  store i8 %"c", i8* %"c.1"
  %"self.2" = load i8*, i8** %"self.1"
  %"methodcall" = call i64 @"String_len"(i8* %"self.2")
  %"len" = alloca i64
  store i64 %"methodcall", i64* %"len"
  %"i" = alloca i64
  store i64 0, i64* %"i"
  br label %"while.cond"
while.cond:
  %"i.1" = load i64, i64* %"i"
  %"len.1" = load i64, i64* %"len"
  %"lttmp" = icmp slt i64 %"i.1", %"len.1"
  br i1 %"lttmp", label %"while.body", label %"while.end"
while.body:
  %"self.3" = load i8*, i8** %"self.1"
  %"i.2" = load i64, i64* %"i"
  %"methodcall.1" = call i8 @"String_byte_at"(i8* %"self.3", i64 %"i.2")
  %"c.2" = load i8, i8* %"c.1"
  %"eqtmp" = icmp eq i8 %"methodcall.1", %"c.2"
  br i1 %"eqtmp", label %"then", label %"else"
while.end:
  %".17" = insertvalue {i1, i64} undef, i1 0, 0
  ret {i1, i64} %".17"
then:
  %"i.3" = load i64, i64* %"i"
  %".11" = insertvalue {i1, i64} undef, i1 1, 0
  %".12" = insertvalue {i1, i64} %".11", i64 %"i.3", 1
  ret {i1, i64} %".12"
else:
  br label %"ifcont"
ifcont:
  %"i.4" = load i64, i64* %"i"
  %"addtmp" = add i64 %"i.4", 1
  store i64 %"addtmp", i64* %"i"
  br label %"while.cond"
}

define {i1, i64} @"String_last_index_of_char"(i8* %"self", i8 %"c")
{
entry:
  %"self.1" = alloca i8*
  store i8* %"self", i8** %"self.1"
  %"c.1" = alloca i8
  store i8 %"c", i8* %"c.1"
  %"self.2" = load i8*, i8** %"self.1"
  %"methodcall" = call i64 @"String_len"(i8* %"self.2")
  %"len" = alloca i64
  store i64 %"methodcall", i64* %"len"
  %"len.1" = load i64, i64* %"len"
  %"subtmp" = sub i64 %"len.1", 1
  %"i" = alloca i64
  store i64 %"subtmp", i64* %"i"
  br label %"while.cond"
while.cond:
  %"i.1" = load i64, i64* %"i"
  %"getmp" = icmp sge i64 %"i.1", 0
  br i1 %"getmp", label %"while.body", label %"while.end"
while.body:
  %"self.3" = load i8*, i8** %"self.1"
  %"i.2" = load i64, i64* %"i"
  %"methodcall.1" = call i8 @"String_byte_at"(i8* %"self.3", i64 %"i.2")
  %"c.2" = load i8, i8* %"c.1"
  %"eqtmp" = icmp eq i8 %"methodcall.1", %"c.2"
  br i1 %"eqtmp", label %"then", label %"else"
while.end:
  %".17" = insertvalue {i1, i64} undef, i1 0, 0
  ret {i1, i64} %".17"
then:
  %"i.3" = load i64, i64* %"i"
  %".11" = insertvalue {i1, i64} undef, i1 1, 0
  %".12" = insertvalue {i1, i64} %".11", i64 %"i.3", 1
  ret {i1, i64} %".12"
else:
  br label %"ifcont"
ifcont:
  %"i.4" = load i64, i64* %"i"
  %"subtmp.1" = sub i64 %"i.4", 1
  store i64 %"subtmp.1", i64* %"i"
  br label %"while.cond"
}

define %"Vector_String" @"String_split"(i8* %"self", i8* %"separator")
{
entry:
  %"self.1" = alloca i8*
  store i8* %"self", i8** %"self.1"
  %"separator.1" = alloca i8*
  store i8* %"separator", i8** %"separator.1"
  %".6" = call %"Vector_String" @"Vector_String_init_"()
  %"result" = alloca %"Vector_String"
  store %"Vector_String" %".6", %"Vector_String"* %"result"
  %"self.2" = load i8*, i8** %"self.1"
  %"methodcall" = call i64 @"String_len"(i8* %"self.2")
  %"self_len" = alloca i64
  store i64 %"methodcall", i64* %"self_len"
  %"separator.2" = load i8*, i8** %"separator.1"
  %"methodcall.1" = call i64 @"String_len"(i8* %"separator.2")
  %"sep_len" = alloca i64
  store i64 %"methodcall.1", i64* %"sep_len"
  %"sep_len.1" = load i64, i64* %"sep_len"
  %"eqtmp" = icmp eq i64 %"sep_len.1", 0
  br i1 %"eqtmp", label %"or_merge", label %"or_right"
or_right:
  %"self_len.1" = load i64, i64* %"self_len"
  %"eqtmp.1" = icmp eq i64 %"self_len.1", 0
  br label %"or_merge"
or_merge:
  %"or_result" = phi  i1 [1, %"entry"], [%"eqtmp.1", %"or_right"]
  br i1 %"or_result", label %"then", label %"else"
then:
  %"result.1" = load %"Vector_String", %"Vector_String"* %"result"
  %"self.3" = load i8*, i8** %"self.1"
  call void @"Vector_String_push"(%"Vector_String"* %"result", i8* %"self.3")
  %"result.2" = load %"Vector_String", %"Vector_String"* %"result"
  br label %"ifcont"
else:
  %"start" = alloca i64
  store i64 0, i64* %"start"
  %"i" = alloca i64
  store i64 0, i64* %"i"
  br label %"while.cond"
ifcont:
  %"iftmp" = phi  %"Vector_String" [%"result.2", %"then"], [%"result.5", %"while.end"]
  ret %"Vector_String" %"iftmp"
while.cond:
  %"i.1" = load i64, i64* %"i"
  %"self_len.2" = load i64, i64* %"self_len"
  %"sep_len.2" = load i64, i64* %"sep_len"
  %"subtmp" = sub i64 %"self_len.2", %"sep_len.2"
  %"letmp" = icmp sle i64 %"i.1", %"subtmp"
  br i1 %"letmp", label %"while.body", label %"while.end"
while.body:
  %"matches" = alloca i1
  store i1 1, i1* %"matches"
  %"j" = alloca i64
  store i64 0, i64* %"j"
  br label %"while.cond.1"
while.end:
  %"self.6" = load i8*, i8** %"self.1"
  %"start.4" = load i64, i64* %"start"
  %"self_len.3" = load i64, i64* %"self_len"
  %"start.5" = load i64, i64* %"start"
  %"subtmp.2" = sub i64 %"self_len.3", %"start.5"
  %"methodcall.7" = call i8* @"String__substring"(i8* %"self.6", i64 %"start.4", i64 %"subtmp.2")
  %"remaining" = alloca i8*
  store i8* %"methodcall.7", i8** %"remaining"
  %"result.4" = load %"Vector_String", %"Vector_String"* %"result"
  %"remaining.1" = load i8*, i8** %"remaining"
  call void @"Vector_String_push"(%"Vector_String"* %"result", i8* %"remaining.1")
  %"result.5" = load %"Vector_String", %"Vector_String"* %"result"
  br label %"ifcont"
while.cond.1:
  %"j.1" = load i64, i64* %"j"
  %"sep_len.3" = load i64, i64* %"sep_len"
  %"lttmp" = icmp slt i64 %"j.1", %"sep_len.3"
  br i1 %"lttmp", label %"and_right", label %"and_merge"
while.body.1:
  %"self.4" = load i8*, i8** %"self.1"
  %"i.2" = load i64, i64* %"i"
  %"j.2" = load i64, i64* %"j"
  %"addtmp" = add i64 %"i.2", %"j.2"
  %"methodcall.3" = call i8 @"String_byte_at"(i8* %"self.4", i64 %"addtmp")
  %"separator.3" = load i8*, i8** %"separator.1"
  %"j.3" = load i64, i64* %"j"
  %"methodcall.4" = call i8 @"String_byte_at"(i8* %"separator.3", i64 %"j.3")
  %"netmp" = icmp ne i8 %"methodcall.3", %"methodcall.4"
  br i1 %"netmp", label %"then.1", label %"else.1"
while.end.1:
  %"matches.2" = load i1, i1* %"matches"
  br i1 %"matches.2", label %"then.2", label %"else.2"
and_right:
  %"matches.1" = load i1, i1* %"matches"
  br label %"and_merge"
and_merge:
  %"and_result" = phi  i1 [0, %"while.cond.1"], [%"matches.1", %"and_right"]
  br i1 %"and_result", label %"while.body.1", label %"while.end.1"
then.1:
  store i1 0, i1* %"matches"
  br label %"ifcont.1"
else.1:
  br label %"ifcont.1"
ifcont.1:
  %"j.4" = load i64, i64* %"j"
  %"addtmp.1" = add i64 %"j.4", 1
  store i64 %"addtmp.1", i64* %"j"
  br label %"while.cond.1"
then.2:
  %"self.5" = load i8*, i8** %"self.1"
  %"start.1" = load i64, i64* %"start"
  %"i.3" = load i64, i64* %"i"
  %"start.2" = load i64, i64* %"start"
  %"subtmp.1" = sub i64 %"i.3", %"start.2"
  %"methodcall.5" = call i8* @"String__substring"(i8* %"self.5", i64 %"start.1", i64 %"subtmp.1")
  %"part" = alloca i8*
  store i8* %"methodcall.5", i8** %"part"
  %"result.3" = load %"Vector_String", %"Vector_String"* %"result"
  %"part.1" = load i8*, i8** %"part"
  call void @"Vector_String_push"(%"Vector_String"* %"result", i8* %"part.1")
  %"i.4" = load i64, i64* %"i"
  %"sep_len.4" = load i64, i64* %"sep_len"
  %"addtmp.2" = add i64 %"i.4", %"sep_len.4"
  store i64 %"addtmp.2", i64* %"start"
  %"start.3" = load i64, i64* %"start"
  store i64 %"start.3", i64* %"i"
  br label %"ifcont.2"
else.2:
  %"i.5" = load i64, i64* %"i"
  %"addtmp.3" = add i64 %"i.5", 1
  store i64 %"addtmp.3", i64* %"i"
  br label %"ifcont.2"
ifcont.2:
  br label %"while.cond"
}

define %"Data" @"String_to_data"(i8* %"self")
{
entry:
  %"self.1" = alloca i8*
  store i8* %"self", i8** %"self.1"
  %".4" = call %"Data" @"Data_init_"()
  %"data" = alloca %"Data"
  store %"Data" %".4", %"Data"* %"data"
  %"i" = alloca i64
  store i64 0, i64* %"i"
  br label %"while.cond"
while.cond:
  %"i.1" = load i64, i64* %"i"
  %"self.2" = load i8*, i8** %"self.1"
  %"methodcall" = call i64 @"String_len"(i8* %"self.2")
  %"lttmp" = icmp slt i64 %"i.1", %"methodcall"
  br i1 %"lttmp", label %"while.body", label %"while.end"
while.body:
  %"data.1" = load %"Data", %"Data"* %"data"
  %"self.3" = load i8*, i8** %"self.1"
  %"i.2" = load i64, i64* %"i"
  %"methodcall.1" = call i8 @"String_byte_at"(i8* %"self.3", i64 %"i.2")
  call void @"Data_push"(%"Data"* %"data", i8 %"methodcall.1")
  %"i.3" = load i64, i64* %"i"
  %"addtmp" = add i64 %"i.3", 1
  store i64 %"addtmp", i64* %"i"
  br label %"while.cond"
while.end:
  %"data_moved" = load %"Data", %"Data"* %"data"
  ret %"Data" %"data_moved"
}

define %"StringBuilder" @"StringBuilder_init_"()
{
entry:
  %".2" = insertvalue {i1, i8*} undef, i1 0, 0
  %".3" = insertvalue %"StringBuilder" undef, {i1, i8*} %".2", 0
  %".4" = insertvalue %"StringBuilder" %".3", i64 0, 1
  %".5" = insertvalue %"StringBuilder" %".4", i64 0, 2
  ret %"StringBuilder" %".5"
}

define %"StringBuilder" @"StringBuilder_init_capacity"(i64 %"capacity")
{
entry:
  %"if_let_result" = alloca %"StringBuilder"
  %"capacity.1" = alloca i64
  store i64 %"capacity", i64* %"capacity.1"
  %"capacity.2" = load i64, i64* %"capacity.1"
  %"letmp" = icmp sle i64 %"capacity.2", 0
  br i1 %"letmp", label %"then", label %"else"
then:
  %".5" = insertvalue {i1, i8*} undef, i1 0, 0
  %".6" = insertvalue %"StringBuilder" undef, {i1, i8*} %".5", 0
  %".7" = insertvalue %"StringBuilder" %".6", i64 0, 1
  %".8" = insertvalue %"StringBuilder" %".7", i64 0, 2
  br label %"ifcont"
else:
  %"capacity.3" = load i64, i64* %"capacity.1"
  %"calltmp" = call i8* @"malloc"(i64 %"capacity.3")
  %"is_not_null" = icmp ne i8* %"calltmp", null
  %"opt_flag" = insertvalue {i1, i8*} undef, i1 %"is_not_null", 0
  %"opt_val" = insertvalue {i1, i8*} %"opt_flag", i8* %"calltmp", 1
  %"is_some" = extractvalue {i1, i8*} %"opt_val", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
ifcont:
  %"iftmp" = phi  %"StringBuilder" [%".8", %"then"], [%"if_let_tmp", %"if_let_merge"]
  ret %"StringBuilder" %"iftmp"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %"opt_val", 1
  %"ptr" = alloca i8*
  store i8* %"unwrapped", i8** %"ptr"
  %"ptr.1" = load i8*, i8** %"ptr"
  %"capacity.4" = load i64, i64* %"capacity.1"
  %".11" = insertvalue {i1, i8*} undef, i1 1, 0
  %".12" = insertvalue {i1, i8*} %".11", i8* %"ptr.1", 1
  %".13" = insertvalue %"StringBuilder" undef, {i1, i8*} %".12", 0
  %".14" = insertvalue %"StringBuilder" %".13", i64 0, 1
  %".15" = insertvalue %"StringBuilder" %".14", i64 %"capacity.4", 2
  store %"StringBuilder" %".15", %"StringBuilder"* %"if_let_result"
  br label %"if_let_merge"
if_let_else:
  %".16" = insertvalue {i1, i8*} undef, i1 0, 0
  %".17" = insertvalue %"StringBuilder" undef, {i1, i8*} %".16", 0
  %".18" = insertvalue %"StringBuilder" %".17", i64 0, 1
  %".19" = insertvalue %"StringBuilder" %".18", i64 0, 2
  store %"StringBuilder" %".19", %"StringBuilder"* %"if_let_result"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp" = load %"StringBuilder", %"StringBuilder"* %"if_let_result"
  br label %"ifcont"
}

define i64 @"StringBuilder_len"(%"StringBuilder" %"self")
{
entry:
  %"self.1" = alloca %"StringBuilder"
  store %"StringBuilder" %"self", %"StringBuilder"* %"self.1"
  %"self.2" = load %"StringBuilder", %"StringBuilder"* %"self.1"
  %".4" = extractvalue %"StringBuilder" %"self.2", 1
  ret i64 %".4"
}

define i1 @"StringBuilder_is_empty"(%"StringBuilder" %"self")
{
entry:
  %"self.1" = alloca %"StringBuilder"
  store %"StringBuilder" %"self", %"StringBuilder"* %"self.1"
  %"self.2" = load %"StringBuilder", %"StringBuilder"* %"self.1"
  %".4" = extractvalue %"StringBuilder" %"self.2", 1
  %"eqtmp" = icmp eq i64 %".4", 0
  ret i1 %"eqtmp"
}

define void @"StringBuilder_append"(%"StringBuilder"* %"self", i8* %"s")
{
entry:
  %"s.1" = alloca i8*
  store i8* %"s", i8** %"s.1"
  %"s.2" = load i8*, i8** %"s.1"
  %"s_ptr" = alloca i8*
  store i8* %"s.2", i8** %"s_ptr"
  %"s_ptr.1" = load i8*, i8** %"s_ptr"
  %"calltmp" = call i64 @"strlen"(i8* %"s_ptr.1")
  %"s_len" = alloca i64
  store i64 %"calltmp", i64* %"s_len"
  %"s_len.1" = load i64, i64* %"s_len"
  %"eqtmp" = icmp eq i64 %"s_len.1", 0
  br i1 %"eqtmp", label %"then", label %"else"
then:
  ret void
else:
  br label %"ifcont"
ifcont:
  %"self.1" = load %"StringBuilder", %"StringBuilder"* %"self"
  %".10" = extractvalue %"StringBuilder" %"self.1", 1
  %"s_len.2" = load i64, i64* %"s_len"
  %"addtmp" = add i64 %".10", %"s_len.2"
  %"addtmp.1" = add i64 %"addtmp", 1
  %"needed" = alloca i64
  store i64 %"addtmp.1", i64* %"needed"
  %"needed.1" = load i64, i64* %"needed"
  %"self.2" = load %"StringBuilder", %"StringBuilder"* %"self"
  %".12" = extractvalue %"StringBuilder" %"self.2", 2
  %"gttmp" = icmp sgt i64 %"needed.1", %".12"
  br i1 %"gttmp", label %"then.1", label %"else.1"
then.1:
  %"self.3" = load %"StringBuilder", %"StringBuilder"* %"self"
  %"needed.2" = load i64, i64* %"needed"
  call void @"StringBuilder_grow"(%"StringBuilder"* %"self", i64 %"needed.2")
  br label %"ifcont.1"
else.1:
  br label %"ifcont.1"
ifcont.1:
  %"self.4" = load %"StringBuilder", %"StringBuilder"* %"self"
  %".16" = extractvalue %"StringBuilder" %"self.4", 0
  %"is_some" = extractvalue {i1, i8*} %".16", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %".16", 1
  %"buf" = alloca i8*
  store i8* %"unwrapped", i8** %"buf"
  %"i" = alloca i64
  store i64 0, i64* %"i"
  br label %"while.cond"
if_let_else:
  br label %"if_let_merge"
if_let_merge:
  ret void
while.cond:
  %"i.1" = load i64, i64* %"i"
  %"s_len.3" = load i64, i64* %"s_len"
  %"lttmp" = icmp slt i64 %"i.1", %"s_len.3"
  br i1 %"lttmp", label %"while.body", label %"while.end"
while.body:
  %"s_ptr.2" = load i8*, i8** %"s_ptr"
  %"i.2" = load i64, i64* %"i"
  %"ptr_idx" = getelementptr i8, i8* %"s_ptr.2", i64 %"i.2"
  %"ptr_elem" = load i8, i8* %"ptr_idx"
  %"self.5" = load %"StringBuilder", %"StringBuilder"* %"self"
  %".22" = extractvalue %"StringBuilder" %"self.5", 1
  %"i.3" = load i64, i64* %"i"
  %"addtmp.2" = add i64 %".22", %"i.3"
  %"container" = load i8*, i8** %"buf"
  %"ptr_elem.1" = getelementptr i8, i8* %"container", i64 %"addtmp.2"
  store i8 %"ptr_elem", i8* %"ptr_elem.1"
  %"i.4" = load i64, i64* %"i"
  %"addtmp.3" = add i64 %"i.4", 1
  store i64 %"addtmp.3", i64* %"i"
  br label %"while.cond"
while.end:
  %"self.6" = load %"StringBuilder", %"StringBuilder"* %"self"
  %".26" = extractvalue %"StringBuilder" %"self.6", 1
  %"s_len.4" = load i64, i64* %"s_len"
  %"addtmp.4" = add i64 %".26", %"s_len.4"
  %"length_ptr" = getelementptr %"StringBuilder", %"StringBuilder"* %"self", i32 0, i32 1
  store i64 %"addtmp.4", i64* %"length_ptr"
  %"self.7" = load %"StringBuilder", %"StringBuilder"* %"self"
  %".28" = extractvalue %"StringBuilder" %"self.7", 1
  %"container.1" = load i8*, i8** %"buf"
  %"ptr_elem.2" = getelementptr i8, i8* %"container.1", i64 %".28"
  %"trunc" = trunc i64 0 to i8
  store i8 %"trunc", i8* %"ptr_elem.2"
  br label %"if_let_merge"
}

define void @"StringBuilder_append_char"(%"StringBuilder"* %"self", i8 %"c")
{
entry:
  %"c.1" = alloca i8
  store i8 %"c", i8* %"c.1"
  %"self.1" = load %"StringBuilder", %"StringBuilder"* %"self"
  %".5" = extractvalue %"StringBuilder" %"self.1", 1
  %"addtmp" = add i64 %".5", 2
  %"needed" = alloca i64
  store i64 %"addtmp", i64* %"needed"
  %"needed.1" = load i64, i64* %"needed"
  %"self.2" = load %"StringBuilder", %"StringBuilder"* %"self"
  %".7" = extractvalue %"StringBuilder" %"self.2", 2
  %"gttmp" = icmp sgt i64 %"needed.1", %".7"
  br i1 %"gttmp", label %"then", label %"else"
then:
  %"self.3" = load %"StringBuilder", %"StringBuilder"* %"self"
  %"needed.2" = load i64, i64* %"needed"
  call void @"StringBuilder_grow"(%"StringBuilder"* %"self", i64 %"needed.2")
  br label %"ifcont"
else:
  br label %"ifcont"
ifcont:
  %"self.4" = load %"StringBuilder", %"StringBuilder"* %"self"
  %".11" = extractvalue %"StringBuilder" %"self.4", 0
  %"is_some" = extractvalue {i1, i8*} %".11", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %".11", 1
  %"buf" = alloca i8*
  store i8* %"unwrapped", i8** %"buf"
  %"c.2" = load i8, i8* %"c.1"
  %"self.5" = load %"StringBuilder", %"StringBuilder"* %"self"
  %".14" = extractvalue %"StringBuilder" %"self.5", 1
  %"container" = load i8*, i8** %"buf"
  %"ptr_elem" = getelementptr i8, i8* %"container", i64 %".14"
  store i8 %"c.2", i8* %"ptr_elem"
  %"self.6" = load %"StringBuilder", %"StringBuilder"* %"self"
  %".16" = extractvalue %"StringBuilder" %"self.6", 1
  %"addtmp.1" = add i64 %".16", 1
  %"length_ptr" = getelementptr %"StringBuilder", %"StringBuilder"* %"self", i32 0, i32 1
  store i64 %"addtmp.1", i64* %"length_ptr"
  %"self.7" = load %"StringBuilder", %"StringBuilder"* %"self"
  %".18" = extractvalue %"StringBuilder" %"self.7", 1
  %"container.1" = load i8*, i8** %"buf"
  %"ptr_elem.1" = getelementptr i8, i8* %"container.1", i64 %".18"
  %"trunc" = trunc i64 0 to i8
  store i8 %"trunc", i8* %"ptr_elem.1"
  br label %"if_let_merge"
if_let_else:
  br label %"if_let_merge"
if_let_merge:
  ret void
}

define void @"StringBuilder_clear"(%"StringBuilder"* %"self")
{
entry:
  %"length_ptr" = getelementptr %"StringBuilder", %"StringBuilder"* %"self", i32 0, i32 1
  store i64 0, i64* %"length_ptr"
  %"self.1" = load %"StringBuilder", %"StringBuilder"* %"self"
  %".4" = extractvalue %"StringBuilder" %"self.1", 0
  %"is_some" = extractvalue {i1, i8*} %".4", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %".4", 1
  %"buf" = alloca i8*
  store i8* %"unwrapped", i8** %"buf"
  %"container" = load i8*, i8** %"buf"
  %"ptr_elem" = getelementptr i8, i8* %"container", i64 0
  %"trunc" = trunc i64 0 to i8
  store i8 %"trunc", i8* %"ptr_elem"
  br label %"if_let_merge"
if_let_else:
  br label %"if_let_merge"
if_let_merge:
  ret void
}

define i8* @"StringBuilder_as_str"(%"StringBuilder" %"self")
{
entry:
  %"if_let_result" = alloca i8*
  %"self.1" = alloca %"StringBuilder"
  store %"StringBuilder" %"self", %"StringBuilder"* %"self.1"
  %"self.2" = load %"StringBuilder", %"StringBuilder"* %"self.1"
  %".4" = extractvalue %"StringBuilder" %"self.2", 0
  %"is_some" = extractvalue {i1, i8*} %".4", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %".4", 1
  %"buf" = alloca i8*
  store i8* %"unwrapped", i8** %"buf"
  %"buf.1" = load i8*, i8** %"buf"
  store i8* %"buf.1", i8** %"if_let_result"
  br label %"if_let_merge"
if_let_else:
  %".7" = getelementptr inbounds [1 x i8], [1 x i8]* @".str.5", i32 0, i32 0
  store i8* %".7", i8** %"if_let_result"
  br label %"if_let_merge"
if_let_merge:
  %"if_let_tmp" = load i8*, i8** %"if_let_result"
  ret i8* %"if_let_tmp"
}

define void @"StringBuilder_grow"(%"StringBuilder"* %"self", i64 %"min_capacity")
{
entry:
  %"min_capacity.1" = alloca i64
  store i64 %"min_capacity", i64* %"min_capacity.1"
  %"self.1" = load %"StringBuilder", %"StringBuilder"* %"self"
  %".5" = extractvalue %"StringBuilder" %"self.1", 2
  %"eqtmp" = icmp eq i64 %".5", 0
  br i1 %"eqtmp", label %"then", label %"else"
then:
  br label %"ifcont"
else:
  %"self.2" = load %"StringBuilder", %"StringBuilder"* %"self"
  %".7" = extractvalue %"StringBuilder" %"self.2", 2
  %"multmp" = mul i64 %".7", 2
  br label %"ifcont"
ifcont:
  %"iftmp" = phi  i64 [16, %"then"], [%"multmp", %"else"]
  %"new_capacity" = alloca i64
  store i64 %"iftmp", i64* %"new_capacity"
  br label %"while.cond"
while.cond:
  %"new_capacity.1" = load i64, i64* %"new_capacity"
  %"min_capacity.2" = load i64, i64* %"min_capacity.1"
  %"lttmp" = icmp slt i64 %"new_capacity.1", %"min_capacity.2"
  br i1 %"lttmp", label %"while.body", label %"while.end"
while.body:
  %"new_capacity.2" = load i64, i64* %"new_capacity"
  %"multmp.1" = mul i64 %"new_capacity.2", 2
  store i64 %"multmp.1", i64* %"new_capacity"
  br label %"while.cond"
while.end:
  %"self.3" = load %"StringBuilder", %"StringBuilder"* %"self"
  %".15" = extractvalue %"StringBuilder" %"self.3", 0
  %"is_some" = extractvalue {i1, i8*} %".15", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %".15", 1
  %"buf" = alloca i8*
  store i8* %"unwrapped", i8** %"buf"
  %"buf.1" = load i8*, i8** %"buf"
  %"new_capacity.3" = load i64, i64* %"new_capacity"
  %"calltmp" = call i8* @"realloc"(i8* %"buf.1", i64 %"new_capacity.3")
  %"is_not_null" = icmp ne i8* %"calltmp", null
  %"opt_flag" = insertvalue {i1, i8*} undef, i1 %"is_not_null", 0
  %"opt_val" = insertvalue {i1, i8*} %"opt_flag", i8* %"calltmp", 1
  %"is_some.1" = extractvalue {i1, i8*} %"opt_val", 0
  br i1 %"is_some.1", label %"if_let_then.1", label %"if_let_else.1"
if_let_else:
  %"new_capacity.5" = load i64, i64* %"new_capacity"
  %"calltmp.1" = call i8* @"malloc"(i64 %"new_capacity.5")
  %"is_not_null.1" = icmp ne i8* %"calltmp.1", null
  %"opt_flag.1" = insertvalue {i1, i8*} undef, i1 %"is_not_null.1", 0
  %"opt_val.1" = insertvalue {i1, i8*} %"opt_flag.1", i8* %"calltmp.1", 1
  %"is_some.2" = extractvalue {i1, i8*} %"opt_val.1", 0
  br i1 %"is_some.2", label %"if_let_then.2", label %"if_let_else.2"
if_let_merge:
  ret void
if_let_then.1:
  %"unwrapped.1" = extractvalue {i1, i8*} %"opt_val", 1
  %"new_buf" = alloca i8*
  store i8* %"unwrapped.1", i8** %"new_buf"
  %"new_buf.1" = load i8*, i8** %"new_buf"
  %"buffer_ptr" = getelementptr %"StringBuilder", %"StringBuilder"* %"self", i32 0, i32 0
  %".20" = insertvalue {i1, i8*} undef, i1 1, 0
  %".21" = insertvalue {i1, i8*} %".20", i8* %"new_buf.1", 1
  store {i1, i8*} %".21", {i1, i8*}* %"buffer_ptr"
  %"new_capacity.4" = load i64, i64* %"new_capacity"
  %"capacity_ptr" = getelementptr %"StringBuilder", %"StringBuilder"* %"self", i32 0, i32 2
  store i64 %"new_capacity.4", i64* %"capacity_ptr"
  br label %"if_let_merge.1"
if_let_else.1:
  br label %"if_let_merge.1"
if_let_merge.1:
  br label %"if_let_merge"
if_let_then.2:
  %"unwrapped.2" = extractvalue {i1, i8*} %"opt_val.1", 1
  %"new_buf.2" = alloca i8*
  store i8* %"unwrapped.2", i8** %"new_buf.2"
  %"new_buf.3" = load i8*, i8** %"new_buf.2"
  %"buffer_ptr.1" = getelementptr %"StringBuilder", %"StringBuilder"* %"self", i32 0, i32 0
  %".28" = insertvalue {i1, i8*} undef, i1 1, 0
  %".29" = insertvalue {i1, i8*} %".28", i8* %"new_buf.3", 1
  store {i1, i8*} %".29", {i1, i8*}* %"buffer_ptr.1"
  %"new_capacity.6" = load i64, i64* %"new_capacity"
  %"capacity_ptr.1" = getelementptr %"StringBuilder", %"StringBuilder"* %"self", i32 0, i32 2
  store i64 %"new_capacity.6", i64* %"capacity_ptr.1"
  %"container" = load i8*, i8** %"new_buf.2"
  %"ptr_elem" = getelementptr i8, i8* %"container", i64 0
  %"trunc" = trunc i64 0 to i8
  store i8 %"trunc", i8* %"ptr_elem"
  br label %"if_let_merge.2"
if_let_else.2:
  br label %"if_let_merge.2"
if_let_merge.2:
  br label %"if_let_merge"
}

define void @"StringBuilder_deinit"(%"StringBuilder"* %"self")
{
entry:
  %"self.1" = load %"StringBuilder", %"StringBuilder"* %"self"
  %".3" = extractvalue %"StringBuilder" %"self.1", 0
  %"is_some" = extractvalue {i1, i8*} %".3", 0
  br i1 %"is_some", label %"if_let_then", label %"if_let_else"
if_let_then:
  %"unwrapped" = extractvalue {i1, i8*} %".3", 1
  %"buf" = alloca i8*
  store i8* %"unwrapped", i8** %"buf"
  %"buf.1" = load i8*, i8** %"buf"
  call void @"free"(i8* %"buf.1")
  br label %"if_let_merge"
if_let_else:
  br label %"if_let_merge"
if_let_merge:
  ret void
}

@".str.0" = private constant [18 x i8] c"Hello from blade!\00"
@".str.1" = private constant [4 x i8] c"%s\0a\00"
@".str.2" = private constant [2 x i8] c"/\00"
@".str.3" = private constant [2 x i8] c" \00"
@".str.4" = private constant [2 x i8] c"r\00"
@".str.5" = private constant [1 x i8] c"\00"