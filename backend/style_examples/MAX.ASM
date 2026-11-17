dosseg
.model small
.data
msg db "enter number:",10,13,"$"
.code
main:
mov ax,@data
mov ds,ax

mov ah,9
mov dx,offset msg
int 21h

mov cl,0
ag:
mov ah,1
int 21h

cmp al,13
je ex

sub al,30h
cmp al,cl
jb ag
mov cl,al
jmp ag

ex:
mov ah,2
add cl,30h
mov dl,cl
int 21h

mov ah,4ch
int 21h
end
