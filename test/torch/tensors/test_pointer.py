import random

import torch
import syft
from test.conftest import hook
from test.conftest import workers

from syft.frameworks.torch.tensors import PointerTensor


def test_init(workers):
    alice = workers["alice"]
    me = workers["me"]

    pointer = PointerTensor(id=1000, location=alice, owner=me)
    pointer.__str__()


def test_create_pointer(workers):
    james = workers["james"]

    x = torch.Tensor([1, 2])
    x.create_pointer()
    x.create_pointer(location=james)


def test_remote_function(workers):
    bob = workers["bob"]

    # init remote object
    x = torch.Tensor([-1, 2, 3]).send(bob)

    # call remote method
    y = torch.add(x, x).get()

    # check answer
    assert (y == torch.tensor([-2.0, 4, 6])).all()


def test_send_get(workers):
    """Test several send get usages"""
    bob = workers["bob"]
    alice = workers["alice"]

    # simple send
    x = torch.Tensor([1, 2])
    x_ptr = x.send(bob)
    x_back = x_ptr.get()
    assert (x == x_back).all()

    # send with variable overwriting
    x = torch.Tensor([1, 2])
    x = x.send(bob)
    x_back = x.get()
    assert (torch.Tensor([1, 2]) == x_back).all()

    # double send
    x = torch.Tensor([1, 2])
    x_ptr = x.send(bob)
    x_ptr_ptr = x_ptr.send(alice)
    x_ptr_back = x_ptr_ptr.get()
    x_back_back = x_ptr_back.get()
    assert (x == x_back_back).all()

    # double send with variable overwriting
    x = torch.Tensor([1, 2])
    x = x.send(bob)
    x = x.send(alice)
    x = x.get()
    x_back = x.get()
    assert (torch.Tensor([1, 2]) == x_back).all()

    # chained double send
    x = torch.Tensor([1, 2])
    x = x.send(bob).send(alice)
    x_back = x.get().get()
    assert (torch.Tensor([1, 2]) == x_back).all()


def test_repeated_send(workers):
    """Tests that repeated calls to .send(bob) works gracefully
    Previously garbage collection deleted the remote object
    when .send() was called twice. This test ensures the fix still
    works."""

    bob = workers["bob"]

    # create tensor
    x = torch.Tensor([1, 2])
    print(x.id)

    # send tensor to bob
    x_ptr = x.send(bob)

    # send tensor again
    x_ptr = x.send(bob)

    # ensure bob has tensor
    assert x.id in bob._objects


def test_remote_autograd(workers):
    """Tests the ability to backpropagate gradients on a remote
    worker."""

    bob = workers["bob"]

    # TEST: simple remote grad calculation

    # create a tensor
    x = torch.tensor([1, 2, 3, 4.0], requires_grad=True)

    # send tensor to bob
    x = x.send(bob)

    # do some calculatinos
    y = (x + x).sum()

    # backpropagate on remote machine
    y.backward()

    # check that remote gradient is correct
    xgrad = bob._objects[x.id_at_location].grad
    xgrad_target = torch.ones(4).float() + 1

    assert (xgrad == xgrad_target).all()

    # TEST: Ensure remote grad calculation gets properly serded

    # create tensor
    x = torch.tensor([1, 2, 3, 4.0], requires_grad=True).send(bob)

    # compute function
    y = x.sum()

    # backpropagate
    y.backward()

    # get the gradient created from backpropagation manually
    x_grad = bob._objects[x.id_at_location].grad

    # get the entire x tensor (should bring the grad too)
    x = x.get()

    # make sure that the grads match
    assert (x.grad == x_grad).all()


def test_gradient_send_recv(workers):
    """Tests that gradients are properly sent and received along
    with their tensors."""

    bob = workers["bob"]

    # create a tensor
    x = torch.tensor([1, 2, 3, 4.0], requires_grad=True)

    # create gradient on tensor
    x.sum().backward(torch.ones(1))

    # save gradient
    orig_grad = x.grad

    # send and get back
    t = x.send(bob).get()

    # check that gradient was properly serde
    assert (t.grad == orig_grad).all()


def test_method_on_attribute(workers):

    bob = workers["bob"]

    # create remote object with children
    x = torch.Tensor([1, 2, 3])
    x = syft.LoggingTensor().on(x).send(bob)

    # call method on data tensor directly
    x.child.point_to_attr = "child.child"
    y = x.add(x)
    assert isinstance(y.get(), torch.Tensor)

    # call method on loggingtensor directly
    x.child.point_to_attr = "child"
    y = x.add(x)
    y = y.get()
    assert isinstance(y.child, syft.LoggingTensor)

    # # call method on zeroth attribute
    # x.child.point_to_attr = ""
    # y = x.add(x)
    # y = y.get()
    #
    # assert isinstance(y, torch.Tensor)
    # assert isinstance(y.child, syft.LoggingTensor)
    # assert isinstance(y.child.child, torch.Tensor)

    # call .get() on pinter to attribute (should error)
    x.child.point_to_attr = "child"
    try:
        x.get()
    except syft.exceptions.CannotRequestTensorAttribute as e:
        assert True


def test_grad_pointer(workers):
    """Tests the automatic creation of a .grad pointer when
    calling .send() on a tensor with requires_grad==True"""

    bob = workers["bob"]

    x = torch.tensor([1, 2, 3.0], requires_grad=True).send(bob)
    grad = torch.tensor([1, 1, 1]).send(bob)
    y = (x + x).sum()
    y.backward()

    assert (bob._objects[x.id_at_location].grad == torch.tensor([2, 2, 2.0])).all()


def test_move(workers):

    bob = workers["bob"]
    alice = workers["alice"]

    x = torch.tensor([1, 2, 3, 4, 5]).send(bob)

    assert x.id_at_location in bob._objects
    assert x.id_at_location not in alice._objects

    x.move(alice)

    assert x.id_at_location not in bob._objects
    assert x.id_at_location in alice._objects
